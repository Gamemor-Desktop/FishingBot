"""Identificacao estrita da janela do jogo e instancia unica."""
from __future__ import annotations

import uuid

import pytest

from fishingbot import single_instance
from fishingbot.window_detect import is_game_window


@pytest.mark.parametrize("proc,cls,expected", [
    ("FiveM_b3751_GTAProcess.exe", "grcWindow", True),
    ("FiveM_b3751_GTAProcess.exe", "", True),            # processo basta
    ("", "grcWindow", True),                              # classe basta (processo elevado)
    ("FiveM_b2802_GTAProcess.exe", "QWidget", True),      # build diferente
    ("chrome.exe", "Chrome_WidgetWin_1", False),          # aba com 'FiveM' no titulo
    ("WindowsTerminal.exe", "CASCADIA_HOSTING_WINDOW_CLASS", False),
    ("FiveM.exe", "QWidget", False),                      # launcher, nao o jogo
    ("", "", False),
])
def test_is_game_window(proc, cls, expected):
    assert is_game_window(proc, cls) is expected


def test_titulo_nao_e_mais_criterio():
    # a assinatura nem recebe o titulo -- garante que ninguem reintroduza
    import inspect
    assert list(inspect.signature(is_game_window).parameters) == ["process_name", "class_name"]


def test_segunda_instancia_e_recusada():
    name = f"Local\\FishingBot_Test_{uuid.uuid4().hex}"
    assert single_instance.acquire(name) is True
    assert single_instance.acquire(name) is False
