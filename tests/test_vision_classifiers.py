"""Testes de caracterizacao do painel de puxar, com capturas reais.

(A zona da fisgada tem seus proprios testes em test_hook_detector.py.)

Cada fixture foi rotulada olhando a imagem (nao o resultado do codigo). Os
casos em que o codigo ATUAL erra estao marcados como xfail(strict=True):
documentam o defeito conhecido e, quando uma fase futura corrigir, o teste
passa a "XPASS" e falha de proposito -- avisando pra remover o marcador.

Origem: screenshots do --debug de sessoes reais (1920x1080, FiveM).
"""
from __future__ import annotations

import pytest

from fishingbot import fishing_logic
from fishingbot.regions import Region

PULL_REGION = {"pulling_state": Region(24, 528, 270, 43)}


# -- painel de puxar (classify_pull_state) -------------------------------

PULL_CASES = [
    # (fixture, esperado, descricao)
    ("010834", "gray", "Calmo sobre agua escura"),
    ("010914", "gray", "Quase fora d'agua (tratado como Calmo)"),
    ("010831", "red", "Puxando forte, luz escura"),
    ("011559", "red", "Puxando forte sobre madeira"),
    ("012457", "red", "Puxando forte, luz clara"),
    ("013107", "red", "Puxando forte sobre fundo claro"),
    ("010919", None, "so a agua escura, sem painel"),
    ("011558", None, "aviso 'Parar de pescar' sobre fundo cinza"),
    ("012437", None, "aviso 'Parar de pescar' sobre madeira"),
    ("013050", None, "aviso 'Parar de pescar' sobre madeira escura"),
    ("012257", None, "madeira clara, sem painel"),
    ("013000", None, "agua/cinza, sem painel"),
    ("013035", None, "cerca branca, sem painel"),
    ("013004", None, "madeira com cerca, sem painel"),
    # Pescaria real de 04/10/2026 (puxada de 1m49s, 108 frames: 0 perdas no meio)
    ("001731", "red", "Puxando forte (pescaria real)"),
    ("001845", "red", "Puxando forte (pescaria real)"),
    ("001735", "gray", "Calmo (pescaria real)"),
    ("001800", "gray", "Calmo (pescaria real)"),
    ("001900", "gray", "Calmo (pescaria real)"),
    ("001917", None, "fim da puxada: painel sumiu (pescaria real)"),
    # Corrigidos em 03/10/2026 pelo texto branco do painel (pulling_text):
    ("012458", "gray", "Calmo translucido sobre fundo marrom (antes: nao detectado)"),
    ("013108", "gray", "Calmo translucido sobre fundo claro (antes: nao detectado)"),
    ("010830", None, "aviso 'Parar de pescar' sobre agua escura (antes: lido como Calmo)"),
    ("013003", None, "madeira/sombra sem painel (antes: lido como Puxando forte)"),
]


@pytest.mark.parametrize("name,expected,_desc", PULL_CASES)
def test_classify_pull_state(make_sct, name, expected, _desc):
    sct = make_sct("pulling_state", name)
    assert fishing_logic.classify_pull_state(sct, PULL_REGION) == expected
