"""input_sim: guarda de foco e garantia de que nenhuma tecla fica presa."""
from __future__ import annotations

import pytest

from fishingbot import input_sim
from fishingbot.input_sim import FocusLostError


class FakeDirectInput:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))


@pytest.fixture
def di(monkeypatch):
    fake = FakeDirectInput()
    monkeypatch.setattr(input_sim, "pydirectinput", fake)
    input_sim._held_keys.clear()
    input_sim.set_focus_guard(None)
    yield fake
    input_sim.set_focus_guard(None)
    input_sim._held_keys.clear()


def test_tap_sobe_a_tecla_mesmo_se_o_sleep_falhar(di, monkeypatch):
    def boom(_):
        raise RuntimeError("interrompido")
    monkeypatch.setattr(input_sim.time, "sleep", boom)
    with pytest.raises(RuntimeError):
        input_sim.tap("space")
    assert di.events == [("down", "space"), ("up", "space")]


def test_sem_foco_tap_nao_envia_nada(di):
    input_sim.set_focus_guard(lambda: False)
    with pytest.raises(FocusLostError):
        input_sim.tap("4")
    assert di.events == []


def test_sem_foco_ensure_only_solta_o_que_estava_preso_e_nao_aperta(di):
    input_sim.ensure_only("s")                 # com foco (sem guarda): aperta
    input_sim.set_focus_guard(lambda: False)   # perdeu o foco
    with pytest.raises(FocusLostError):
        input_sim.ensure_only("w")
    assert di.events == [("down", "s"), ("up", "s")]
    assert input_sim._held_keys == set()


def test_soltar_tudo_nunca_exige_foco(di):
    input_sim.ensure_only("s")
    input_sim.set_focus_guard(lambda: False)
    input_sim.ensure_only(None)                # soltar e sempre permitido
    assert di.events == [("down", "s"), ("up", "s")]


def test_guarda_que_levanta_excecao_conta_como_sem_foco(di):
    def bad():
        raise OSError("win32 falhou")
    input_sim.set_focus_guard(bad)
    with pytest.raises(FocusLostError):
        input_sim.key_down("w")
    assert di.events == []


def test_com_foco_funciona_normalmente_e_troca_de_tecla(di):
    input_sim.set_focus_guard(lambda: True)
    input_sim.ensure_only("s")
    input_sim.ensure_only("w")
    assert di.events == [("down", "s"), ("up", "s"), ("down", "w")]
    input_sim.release_all()
    assert di.events[-1] == ("up", "w")
    assert input_sim._held_keys == set()
