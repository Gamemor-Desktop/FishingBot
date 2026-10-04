"""
Sanidade da captura de tela. Se o bot esta "olhando" uma tela preta (jogo em
fullscreen exclusivo, PC bloqueado, HDR/overlay) ou uma imagem congelada
(jogo travado, menu de pausa), a deteccao por cor so devolve zero -- e o bot
interpretaria isso como "peixe fugiu"/"painel nunca apareceu", repetindo
lances inuteis sem ninguem perceber. Aqui detectamos essas condicoes e o
controlador para com uma mensagem clara.

Tambem valida que as regioes de captura cabem dentro da tela: o mss NAO da
erro ao capturar fora dos limites, devolve preto.
"""
from __future__ import annotations

import cv2
import numpy as np

THUMB_SIZE = (64, 36)  # (largura, altura) da miniatura usada nas checagens


def grab_thumbnail(sct, left: int, top: int, width: int, height: int) -> np.ndarray:
    """Captura a janela inteira e devolve uma miniatura cinza (barato: 1x/s)."""
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    gray = cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2GRAY)
    return cv2.resize(gray, THUMB_SIZE, interpolation=cv2.INTER_AREA)


class CaptureMonitor:
    """Recebe miniaturas ao longo do tempo e devolve uma mensagem de erro
    quando a imagem fica preta ou congelada por tempo demais (None = ok).
    O tempo e injetado (`now`) pra ser testavel sem esperar."""

    def __init__(self, black_seconds: float = 3.0, frozen_seconds: float = 15.0,
                 black_mean: float = 3.0, frozen_tolerance: int = 1):
        self.black_seconds = black_seconds
        self.frozen_seconds = frozen_seconds
        self.black_mean = black_mean
        self.frozen_tolerance = frozen_tolerance
        self.reset()

    def reset(self) -> None:
        self._black_since: float | None = None
        self._frozen_since: float | None = None
        self._prev: np.ndarray | None = None
        self._prev_time = 0.0

    def update(self, thumb: np.ndarray, now: float) -> str | None:
        if float(thumb.mean()) < self.black_mean:
            if self._black_since is None:
                self._black_since = now
            if now - self._black_since >= self.black_seconds:
                return ("A captura de tela esta PRETA -- o FiveM provavelmente esta em "
                        "tela cheia exclusiva (use janela sem bordas) ou o PC foi bloqueado.")
        else:
            self._black_since = None

        if self._prev is not None and self._prev.shape == thumb.shape:
            diff = int(np.abs(thumb.astype(np.int16) - self._prev.astype(np.int16)).max())
            if diff <= self.frozen_tolerance:
                if self._frozen_since is None:
                    self._frozen_since = self._prev_time  # congelou desde a leitura anterior
                if now - self._frozen_since >= self.frozen_seconds:
                    return (f"A imagem do jogo esta CONGELADA ha {self.frozen_seconds:.0f}s "
                            f"-- o jogo travou ou esta num menu/carregamento.")
            else:
                self._frozen_since = None
        self._prev = thumb
        self._prev_time = now
        return None


def validate_regions(regions: dict, bounds: dict) -> list[str]:
    """Problemas das regioes em relacao a area total de tela (`bounds` no
    formato do mss: left/top/width/height). Lista vazia = tudo certo."""
    problems = []
    b_left, b_top = bounds["left"], bounds["top"]
    b_right, b_bottom = b_left + bounds["width"], b_top + bounds["height"]
    for name, r in regions.items():
        if r.x < b_left or r.y < b_top or r.x + r.w > b_right or r.y + r.h > b_bottom:
            problems.append(f"regiao '{name}' ({r.x},{r.y} {r.w}x{r.h}) fica fora da tela")
    return problems
