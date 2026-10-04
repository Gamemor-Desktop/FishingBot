"""Aviso 'X Parar de pescar' = a linha esta na agua = a pesca comecou."""
from __future__ import annotations

import pytest

from conftest import load_fixture
from fishingbot import fishing_logic, vision
from fishingbot.app_state import SharedState
from fishingbot.regions import DEFAULT_COLORS, Region

CFG = DEFAULT_COLORS["stop_prompt"]

# Rotulados olhando as imagens (texto vermelho + X da tecla), 4 fundos diferentes
COM_AVISO = ["010830", "011558", "012437", "013050"]
SEM_AVISO = ["010831", "010834", "010914", "010919", "011559", "012257", "012457",
             "012458", "013000", "013003", "013004", "013035", "013107", "013108"]

REGIONS = {"hook_zone": Region(0, 0, 252, 108), "pulling_state": Region(0, 0, 270, 43)}


@pytest.mark.parametrize("name", COM_AVISO)
def test_aviso_parar_de_pescar_e_detectado(name):
    assert vision.stop_prompt_visible(load_fixture("pulling_state", name), CFG) is True


@pytest.mark.parametrize("name", SEM_AVISO)
def test_painel_de_puxar_e_cenario_nao_sao_o_aviso(name):
    # inclui 'Puxando forte' (tem vermelho, sem o X) e cerca branca (tem branco, sem vermelho)
    assert vision.stop_prompt_visible(load_fixture("pulling_state", name), CFG) is False


def _shared() -> SharedState:
    s = SharedState()
    s.update(user_wants_running=True)
    return s


def test_sem_o_aviso_o_bot_avisa_que_a_pesca_nao_comecou(make_sct):
    shared = _shared()
    sct = make_sct("hook_zone", "010809")          # cena vazia: sem bolinha, sem aviso
    fishing_logic.wait_for_bite(sct, REGIONS, shared, True, 0.6, cast_check_seconds=0.2)
    assert "NAO ter comecado" in shared.snapshot()["status_message"]


def test_com_o_aviso_nao_ha_alerta(make_sct, monkeypatch):
    shared = _shared()
    monkeypatch.setattr(fishing_logic.vision, "stop_prompt_visible", lambda *_: True)
    sct = make_sct("hook_zone", "010809")
    fishing_logic.wait_for_bite(sct, REGIONS, shared, True, 0.6, cast_check_seconds=0.2)
    assert "NAO ter comecado" not in shared.snapshot()["status_message"]


def test_o_alerta_nao_cancela_o_lance_e_a_mordida_ainda_vale(make_sct):
    """So informa: com bolinha na tela o lance segue normalmente, mesmo sem o aviso."""
    shared = _shared()
    sct = make_sct("hook_zone", "010829")          # bolinha presente
    assert fishing_logic.wait_for_bite(sct, REGIONS, shared, True, 5.0, cast_check_seconds=0.0) is True


def test_alerta_some_quando_o_aviso_aparece(make_sct, monkeypatch):
    shared = _shared()
    seen = iter([False, False, True])               # o aviso so aparece na 3a checagem (~0.5s)
    monkeypatch.setattr(fishing_logic.vision, "stop_prompt_visible", lambda *_: next(seen, True))
    sct = make_sct("hook_zone", "010809")
    fishing_logic.wait_for_bite(sct, REGIONS, shared, True, 1.5, cast_check_seconds=0.0)
    assert "NAO ter comecado" not in shared.snapshot()["status_message"]
