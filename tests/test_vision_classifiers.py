"""Testes de caracterizacao da deteccao por cor, com capturas reais.

Cada fixture foi rotulada olhando a imagem (nao o resultado do codigo). Os
casos em que o codigo ATUAL erra estao marcados como xfail(strict=True):
documentam o defeito conhecido e, quando uma fase futura corrigir, o teste
passa a "XPASS" e falha de proposito -- avisando pra remover o marcador.

Origem: screenshots do --debug de sessoes reais (1920x1080, FiveM).
"""
from __future__ import annotations

import pytest

from fishingbot import fishing_logic
from fishingbot.regions import DEFAULT_COLORS, Region

PULL_REGION = {"pulling_state": Region(24, 528, 270, 43)}
HOOK_REGION = Region(756, 528, 252, 108)

BITE_MIN = DEFAULT_COLORS["hook_zone"]["bite_min_ratio"]
HIT_MIN = DEFAULT_COLORS["hook_zone"]["hit_min_ratio"]


def _known_bug(reason: str):
    return pytest.mark.xfail(strict=True, reason=reason)


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
    pytest.param(
        "012458", "gray", "Calmo translucido sobre fundo marrom",
        id="012458",
        marks=_known_bug("falso negativo: painel translucido sobre fundo claro "
                         "fica fora da faixa HSV de 'Calmo' (ratio 0.0)"),
    ),
    pytest.param(
        "013108", "gray", "Calmo translucido sobre fundo claro",
        id="013108",
        marks=_known_bug("falso negativo: painel translucido sobre fundo claro "
                         "fica fora da faixa HSV de 'Calmo' (ratio 0.06)"),
    ),
    pytest.param(
        "010830", None, "aviso 'Parar de pescar' sobre agua escura",
        id="010830",
        marks=_known_bug("falso positivo: aviso escuro cai na faixa de 'Calmo' "
                         "(ratio 0.86) e conta como painel visto"),
    ),
    pytest.param(
        "013003", None, "madeira/sombra sem painel",
        id="013003",
        marks=_known_bug("falso positivo: textura de madeira marrom bate na "
                         "faixa de 'Puxando forte' (ratio ~0.30, no limite)"),
    ),
]


@pytest.mark.parametrize("name,expected,_desc", PULL_CASES)
def test_classify_pull_state(make_sct, name, expected, _desc):
    sct = make_sct("pulling_state", name)
    assert fishing_logic.classify_pull_state(sct, PULL_REGION) == expected


# -- zona da fisgada (hook_zone) -----------------------------------------

def _ratio(make_sct, name: str) -> float:
    return fishing_logic._hook_zone_ratio(make_sct("hook_zone", name), HOOK_REGION)


def test_hook_zone_bolinha_pequena_passa_limiar_de_mordida(make_sct):
    # 010829: bolinha vermelha + linha visiveis, ainda sem o peixe alinhado
    ratio = _ratio(make_sct, "010829")
    assert BITE_MIN <= ratio < HIT_MIN


def test_hook_zone_bolinha_alinhada_passa_limiar_de_fisgada(make_sct):
    # 012456: bolinha + peixe vermelho + '!' (momento certo de apertar ESPACO)
    assert _ratio(make_sct, "012456") >= HIT_MIN


@pytest.mark.parametrize("name", ["010809", "011556"])
def test_hook_zone_sem_bolinha_fica_abaixo_da_mordida(make_sct, name):
    assert _ratio(make_sct, name) < BITE_MIN


@pytest.mark.parametrize("name", [
    pytest.param("012430", marks=_known_bug(
        "ruido da roupa (ratio ~0.007) ja passa bite_min_ratio=0.0045")),
    pytest.param("013035", marks=_known_bug(
        "ruido da roupa (ratio ~0.011) ja passa bite_min_ratio=0.0045")),
    pytest.param("013049", marks=_known_bug(
        "ruido da roupa (ratio ~0.012) ja passa bite_min_ratio=0.0045")),
])
def test_hook_zone_ruido_da_roupa_nao_vira_mordida(make_sct, name):
    assert _ratio(make_sct, name) < BITE_MIN


@_known_bug("ruido da roupa (ratio ~0.0227) passa ate hit_min_ratio=0.018, "
            "disparando ESPACO sem a bolinha real")
def test_hook_zone_ruido_da_roupa_nao_vira_fisgada(make_sct):
    assert _ratio(make_sct, "013000") < HIT_MIN
