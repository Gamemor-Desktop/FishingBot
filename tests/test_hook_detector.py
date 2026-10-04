"""Detector da zona da fisgada (vision.read_hook), validado com capturas reais.

Rotulos feitos olhando as imagens: bolinha vermelha presente ou nao. A roupa
do personagem (hoodie listrado) tem o mesmo matiz da bolinha e gerava ruido
MAIOR que ela quando o criterio era so "proporcao de pixels vermelhos"; o
detector atual usa brilho + forma (ver regions.DEFAULT_COLORS['hook_zone']).
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from conftest import load_fixture
from fishingbot import vision
from fishingbot.regions import DEFAULT_COLORS

COLORS = DEFAULT_COLORS["hook_zone"]
HIT_MIN = COLORS["hit_min_ratio"]

# So a bolinha (fase de mordida)
BALL_ONLY = ["010829", "011558", "013106"]
# Bolinha + peixe vermelho alinhado (momento de apertar ESPACO)
BALL_AND_FISH = ["012456"]
# Sem bolinha: cena vazia ou so roupa/cenario com as mesmas cores
NO_BALL = ["010809", "011556", "012417", "012430", "012434",
           "013000", "013035", "013041", "013049", "013057", "013104"]


@pytest.mark.parametrize("name", BALL_ONLY + BALL_AND_FISH)
def test_bolinha_e_detectada(name):
    assert vision.read_hook(load_fixture("hook_zone", name), COLORS).ball is True


@pytest.mark.parametrize("name", NO_BALL)
def test_roupa_e_cenario_nao_viram_bolinha(name):
    assert vision.read_hook(load_fixture("hook_zone", name), COLORS).ball is False


@pytest.mark.parametrize("name", BALL_ONLY)
def test_so_a_bolinha_nao_dispara_a_fisgada(name):
    assert vision.read_hook(load_fixture("hook_zone", name), COLORS).bright_ratio < HIT_MIN


@pytest.mark.parametrize("name", BALL_AND_FISH)
def test_bolinha_mais_peixe_dispara_a_fisgada(name):
    assert vision.read_hook(load_fixture("hook_zone", name), COLORS).bright_ratio >= HIT_MIN


@pytest.mark.parametrize("name", NO_BALL)
def test_ruido_nunca_chega_perto_do_limiar_de_fisgada(name):
    # antes, a proporcao de ruido (ate 0.0227) passava do hit_min antigo (0.018)
    ratio = vision.read_hook(load_fixture("hook_zone", name), COLORS).bright_ratio
    assert ratio < HIT_MIN / 5


def test_margem_entre_ruido_e_bolinha():
    """O ruido maximo precisa ficar bem abaixo da menor proporcao de bolinha
    (senao qualquer ajuste fino de cor quebra a separacao)."""
    noise = max(vision.read_hook(load_fixture("hook_zone", n), COLORS).bright_ratio for n in NO_BALL)
    ball = min(vision.read_hook(load_fixture("hook_zone", n), COLORS).bright_ratio for n in BALL_ONLY)
    assert noise * 4 < ball


def test_bolinha_escala_com_a_resolucao():
    """Em uma regiao 2x maior (4K) a bolinha tem ~4x a area em pixels; os
    limites de area escalam com o quadrado da razao e ela segue detectada."""
    frame = load_fixture("hook_zone", "010829")
    big = cv2.resize(frame, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    assert vision.read_hook(big, COLORS).ball is True
    small = cv2.resize(frame, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
    assert vision.read_hook(small, COLORS).ball is True


def test_quadro_preto_nao_tem_bolinha_nem_ratio():
    black = np.zeros((108, 252, 3), np.uint8)
    reading = vision.read_hook(black, COLORS)
    assert reading.ball is False and reading.bright_ratio == 0.0
