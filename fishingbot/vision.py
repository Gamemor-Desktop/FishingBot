"""
Funcoes de visao computacional usadas pelo bot de pesca.
Tudo aqui trabalha em cima de arrays numpy BGR (formato que o mss/opencv usam).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import cv2
import mss


def grab(sct: mss.MSS, roi: list[int]) -> np.ndarray:
    """Captura uma regiao da tela. roi = [x, y, w, h] em coordenadas absolutas."""
    x, y, w, h = roi
    shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
    frame = np.array(shot)  # BGRA
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def hsv_mask(frame_bgr: np.ndarray, lower: list[int], upper: list[int]) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower_np = np.array(lower, dtype=np.uint8)
    upper_np = np.array(upper, dtype=np.uint8)
    return cv2.inRange(hsv, lower_np, upper_np)


def hsv_mask_multi(frame_bgr: np.ndarray, ranges: list[tuple[list[int], list[int]]]) -> np.ndarray:
    """Como hsv_mask, mas combina (OR) varias faixas de HSV numa mascara so.
    Necessario pra cores cujo matiz (Hue) fica perto do "wrap" 0/179 do
    OpenCV (ex: vermelho) -- dependendo da luz ambiente do jogo, a MESMA cor
    pode cair um pouco pra um lado (H perto de 0) ou pro outro (H perto de
    179), e uma unica faixa nao-circular so cobre um dos dois lados."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lower, dtype=np.uint8),
                                                  np.array(upper, dtype=np.uint8)))
    return mask


def pixel_ratio(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / float(mask.size)


# Largura (px) da regiao hook_zone na resolucao de referencia 1920x1080
# (regions.DEFAULT_FRACTIONS: 252px). Os limites de area da bolinha em
# regions.DEFAULT_COLORS foram medidos nela; em outra resolucao a regiao muda
# de tamanho e as areas escalam com o quadrado da razao.
HOOK_REF_WIDTH = 252


@dataclass
class HookReading:
    ball: bool          # existe um disco compacto e brilhante (a bolinha)
    bright_ratio: float  # proporcao de pixels brilhantes vermelho-laranja
    mask: np.ndarray    # mascara usada (pra debug)


def read_hook(frame_bgr: np.ndarray, colors: dict) -> HookReading:
    """Le a zona da fisgada. A mascara so aceita pixels BRILHANTES (V alto):
    a roupa do personagem tem o mesmo matiz, mas e bem mais escura. `ball`
    exige ainda a FORMA da bolinha (componente quase quadrado e bem
    preenchido), o que descarta restos de roupa/cenario mesmo que passem na
    cor. Ver o racional e as medicoes em regions.DEFAULT_COLORS['hook_zone']."""
    mask = hsv_mask(frame_bgr, colors["lower"], colors["upper"])
    ratio = pixel_ratio(mask)
    ball = False
    if ratio > 0:
        scale = max(frame_bgr.shape[1] / HOOK_REF_WIDTH, 0.1)
        area_min = colors["ball_min_area"] * scale * scale
        area_max = colors["ball_max_area"] * scale * scale
        n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            w, h, area = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]),                 int(stats[i, cv2.CC_STAT_AREA])
            if not (area_min <= area <= area_max) or w == 0 or h == 0:
                continue
            if colors["ball_aspect_min"] <= w / h <= colors["ball_aspect_max"]                     and area / (w * h) >= colors["ball_min_fill"]:
                ball = True
                break
    return HookReading(ball=ball, bright_ratio=ratio, mask=mask)


def panel_text_features(frame_bgr: np.ndarray, cfg: dict) -> tuple[float, float]:
    """(proporcao de pixels de texto branco na metade direita do painel,
    fracao desses pixels que tem fundo ESCURO por perto). O painel de verdade
    tem texto branco sobre a caixa escura; cerca/parede branca tem muito
    branco mas sem fundo escuro em volta, e o resto do cenario nao tem branco
    nenhum. Ver regions.DEFAULT_COLORS['pulling_text']."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    right = hsv[:, int(frame_bgr.shape[1] * cfg["x_start"]):]
    white = cv2.inRange(right, np.array([0, 0, cfg["white_min_v"]], dtype=np.uint8),
                        np.array([179, cfg["white_max_s"], 255], dtype=np.uint8))
    n_white = int(np.count_nonzero(white))
    if n_white == 0:
        return 0.0, 0.0
    dark = cv2.inRange(right, np.array([0, 0, 0], dtype=np.uint8),
                       np.array([179, 255, cfg["dark_max_v"]], dtype=np.uint8))
    dark = cv2.dilate(dark, np.ones((7, 7), np.uint8))
    near_dark = int(np.count_nonzero(cv2.bitwise_and(dark, white))) / n_white
    return n_white / white.size, near_dark


def stop_prompt_visible(frame_bgr: np.ndarray, cfg: dict) -> bool:
    """True se o aviso "X Parar de pescar" esta na regiao (a linha esta na
    agua = a pesca comecou). Exige AS DUAS marcas: texto vermelho vivo e o X
    branco da tecla, a esquerda. Ver regions.DEFAULT_COLORS['stop_prompt']."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    red = np.zeros((h, w), dtype=np.uint8)
    for lower, upper in cfg["red_ranges"]:
        red = cv2.bitwise_or(red, cv2.inRange(hsv, np.array(lower, dtype=np.uint8),
                                              np.array(upper, dtype=np.uint8)))
    band = red[:, int(w * cfg["red_x_from"]):int(w * cfg["red_x_to"])]
    left = hsv[:, :int(w * cfg["x_key_to"])]
    white = cv2.inRange(left, np.array([0, 0, 225], dtype=np.uint8),
                        np.array([179, 40, 255], dtype=np.uint8))
    return (pixel_ratio(band) >= cfg["min_red"]
            and cfg["min_white"] <= pixel_ratio(white) <= cfg["max_white"])
