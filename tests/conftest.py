"""Utilitarios compartilhados pelos testes.

Os testes de visao usam PNGs REAIS capturados com --debug (tests/fixtures),
sem tocar na tela: um FakeSct devolve o PNG no formato BGRA que o mss
devolveria, entao classify_pull_state / _hook_zone_ratio rodam o codigo de
producao de verdade, sem nenhum mock da logica.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSct:
    """Imita mss.mss().grab(): ignora o recorte pedido e devolve sempre a
    imagem fixa, em BGRA (np.array(shot) no vision.grab espera isso)."""

    def __init__(self, frame_bgr: np.ndarray):
        self._bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)

    def grab(self, _monitor):
        return self._bgra


def load_fixture(kind: str, name: str) -> np.ndarray:
    path = FIXTURES / kind / f"{name}.png"
    frame = cv2.imread(str(path))
    assert frame is not None, f"fixture nao encontrada: {path}"
    return frame


@pytest.fixture
def make_sct():
    def _make(kind: str, name: str) -> FakeSct:
        return FakeSct(load_fixture(kind, name))
    return _make
