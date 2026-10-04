"""
Leitura da PROFUNDIDADE no HUD de pesca do FiveM, sem OCR externo.

O HUD tem uma coluna de caixas (cada uma 270x43 px em 1920x1080):

    LINHA          18,5 /181 m          linha 1
    PROFUNDIDADE   3 m                  linha 2   <- lida aqui
    [E] Parar nesta profundidade        linha 3   <- prompt: sinal de que da pra parar

A fonte e monoespacada e de tamanho fixo, entao cada digito e reconhecido por
comparacao com um modelo (matriz 12x18 normalizada), sem Tesseract. Os modelos
(`depth_templates.py`) sao gerados por `tools/build_depth_templates.py` a partir
de capturas reais em `tests/fixtures/` -- nenhum numero aqui foi chutado.

Seguranca: ler "na duvida" nunca vira numero. Um glifo so vale com distancia
<= MAX_DIST ao modelo E margem >= MIN_MARGIN sobre o segundo colocado; qualquer
coisa fora do padrao [digitos][espaco]['m'] devolve value=None. Quem usa o
resultado (fishing_logic.run_depth_lock) nunca aperta E sem ler com certeza.
"""
from __future__ import annotations

import base64
import functools
from dataclasses import dataclass

import cv2
import numpy as np

REF_SIZE = (270, 43)        # (largura, altura) de uma caixa do HUD em 1920x1080
GLYPH_SIZE = (12, 18)       # (largura, altura) do glifo normalizado
WHITE_V, WHITE_S = 215, 70  # "branco" do texto: brilho minimo / saturacao maxima (HSV)
VALUE_X0 = 100              # o valor fica na metade direita da caixa (o rotulo, cinza, nao passa do limiar)
DIGIT_H = (11, 17)          # altura em px de um digito (14-15 observado)
GLYPH_H = (8, 17)           # digitos e o 'm' (10 px)
GLYPH_W = (4, 13)
MIN_AREA = 12
MAX_DIST = 0.20             # distancia media maxima ao modelo (observado 0.08-0.14 em leituras reais)
MIN_MARGIN = 0.03           # vantagem minima sobre o 2o modelo (menor observado: 0.043)
MAX_DIGITS = 3
# A fonte e monoespacada: o que vale e a distancia entre os CENTROS das celulas, nao a folga
# entre as bordas (um '1' tem 5 px de largura dentro de uma celula de ~12).
DIGIT_PITCH = (9.0, 15.0)   # centro a centro entre digitos vizinhos (observado 11.5-13.5)
M_PITCH = (17.0, 28.0)      # centro do ultimo digito ao centro do 'm' (observado 22-23.5)
PROMPT_MIN_SCORE = 0.85     # recall e precisao minimos do prompt (positivos 1.00, melhor negativo 0.54)


@dataclass
class Glyph:
    x: int
    y: int
    w: int
    h: int
    mask: np.ndarray


@dataclass
class DepthReading:
    value: int | None       # metros, ou None se nao leu com certeza
    reason: str = ""        # por que nao leu (so pra log/depuracao)
    min_margin: float = 0.0  # menor margem de confianca entre os digitos usados


# -- primitivas (usadas tambem pelo gerador de modelos) -----------------------------------------

def to_reference(row_bgr: np.ndarray) -> np.ndarray:
    """Leva a caixa recortada a resolucao de referencia (270x43)."""
    if row_bgr.shape[1] == REF_SIZE[0] and row_bgr.shape[0] == REF_SIZE[1]:
        return row_bgr
    interp = cv2.INTER_AREA if row_bgr.shape[1] > REF_SIZE[0] else cv2.INTER_CUBIC
    return cv2.resize(row_bgr, REF_SIZE, interpolation=interp)


def white_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Mascara 0/255 dos pixels de texto branco."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([0, 0, WHITE_V]), np.array([179, WHITE_S, 255]))


def extract_glyphs(mask: np.ndarray, x_offset: int = 0, h_range=GLYPH_H) -> list[Glyph]:
    """Componentes conexos com cara de caractere, ordenados da esquerda pra direita."""
    n, _lab, st, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if h_range[0] <= h <= h_range[1] and GLYPH_W[0] <= w <= GLYPH_W[1] and area >= MIN_AREA:
            out.append(Glyph(x + x_offset, y, w, h, mask[y:y + h, x:x + w]))
    return sorted(out, key=lambda g: g.x)


def normalize_glyph(mask: np.ndarray) -> np.ndarray:
    """Recorte do glifo -> matriz float32 (18x12) em [0,1]."""
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    return cv2.resize(padded, GLYPH_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


# -- modelos ------------------------------------------------------------------------------------

def _decode(b64: str, dtype=np.uint8) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_GRAYSCALE)


@functools.lru_cache(maxsize=1)
def _templates() -> tuple[dict, np.ndarray, np.ndarray]:
    from . import depth_templates as t  # gerado por tools/build_depth_templates.py
    digits = {k: _decode(v).astype(np.float32) / 255.0 for k, v in t.DIGITS.items()}
    m = _decode(t.M).astype(np.float32) / 255.0
    prompt = (_decode(t.PROMPT) > 127).astype(np.uint8)
    return digits, m, prompt


def _classify(glyph: Glyph, models: dict) -> tuple[str, float, float]:
    """(rotulo, distancia ao melhor modelo, margem sobre o segundo)."""
    g = normalize_glyph(glyph.mask)
    scores = sorted((float(np.abs(g - t).mean()), k) for k, t in models.items())
    return scores[0][1], scores[0][0], scores[1][0] - scores[0][0]


# -- leitura -------------------------------------------------------------------------------------

def read_depth(row_bgr: np.ndarray) -> DepthReading:
    """Le a caixa PROFUNDIDADE (linha 2 do HUD). value=None se nao houver um
    numero legivel (ex: durante o arremesso aparece '-', ou o HUD nao esta na tela)."""
    row = to_reference(row_bgr)
    digits, m_model, _prompt = _templates()
    models = {**digits, "m": m_model}

    mask = white_mask(row[:, VALUE_X0:])
    classified = []
    for g in extract_glyphs(mask, VALUE_X0):
        label, dist, margin = _classify(g, models)
        # digito so vale com distancia E margem; o 'm' so precisa da distancia
        if dist <= MAX_DIST and (label == "m" or margin >= MIN_MARGIN):
            classified.append((g, label, margin))

    ms = [c for c in classified if c[1] == "m"]
    if not ms:
        return DepthReading(None, "sem o 'm' da unidade")
    m_glyph = ms[-1][0]

    left = sorted((c for c in classified if c[1] != "m" and c[0].x < m_glyph.x), key=lambda c: c[0].x)
    run: list = []
    next_center, pitch = m_glyph.x + m_glyph.w / 2, M_PITCH
    for g, label, margin in reversed(left):
        center = g.x + g.w / 2
        if not pitch[0] <= next_center - center <= pitch[1]:
            break
        run.insert(0, (g, label, margin))
        next_center, pitch = center, DIGIT_PITCH
    if not run:
        return DepthReading(None, "sem digitos antes do 'm'")
    if len(run) > MAX_DIGITS:
        return DepthReading(None, "digitos demais")
    value = int("".join(label for _g, label, _m in run))
    return DepthReading(value, "", min(margin for _g, _l, margin in run))


def depth_prompt_score(row_bgr: np.ndarray) -> tuple[float, float]:
    """(recall, precisao) do texto branco da caixa contra o modelo do prompt
    '[E] Parar nesta profundidade' (com tolerancia de 1 px)."""
    row = to_reference(row_bgr)
    _d, _m, template = _templates()
    k = np.ones((3, 3), np.uint8)
    seen = (white_mask(row) > 0).astype(np.uint8)
    recall = float((cv2.dilate(seen, k) & template).sum()) / max(1, int(template.sum()))
    precision = float((seen & cv2.dilate(template, k)).sum()) / max(1, int(seen.sum()))
    return recall, precision


def depth_prompt_visible(row_bgr: np.ndarray) -> bool:
    """True se a linha 3 do HUD mostra '[E] Parar nesta profundidade' -- a UNICA
    situacao em que apertar E faz o que queremos. O texto do prompt e identico
    em todo o jogo, entao a comparacao e por pixels e exige recall E precisao."""
    recall, precision = depth_prompt_score(row_bgr)
    return min(recall, precision) >= PROMPT_MIN_SCORE
