"""Controlador: supervisor, watchdog, panico, shutdown e estado de erro."""
from __future__ import annotations

import threading
import time

import pytest

from fishingbot import controller as controller_mod
from fishingbot import input_sim
from fishingbot.app_state import AppState, SharedState
from fishingbot.controller import (
    Controller,
    _WindowWatchdog,
    check_window_health,
)
from fishingbot.input_sim import FocusLostError
from fishingbot.window_detect import WindowInfo


def _window(**kw) -> WindowInfo:
    base = dict(hwnd=1, title="FiveM", process_name="FiveM_GTAProcess.exe",
                left=0, top=0, width=1920, height=1080)
    base.update(kw)
    return WindowInfo(**base)


def _wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    releases = []
    monkeypatch.setattr(input_sim, "release_all", lambda: releases.append(1))
    shared = SharedState()
    c = Controller(shared, dry_run=True)
    c.releases = releases
    yield c
    c.request_quit()
    if c._thread is not None:
        c._thread.join(timeout=2)


def _start_thread(c: Controller):
    c._thread = threading.Thread(target=c._run, daemon=True)
    c._thread.start()


# -- supervisor --------------------------------------------------------------

def test_excecao_inesperada_vai_pra_erro_solta_teclas_e_a_thread_sobrevive(ctrl, monkeypatch):
    def boom(self):
        raise RuntimeError("mss quebrou")
    monkeypatch.setattr(Controller, "_run_once", boom)

    ctrl.shared.update(user_wants_running=True)
    _start_thread(ctrl)

    assert _wait_for(lambda: ctrl.shared.snapshot()["state"] == AppState.ERRO)
    snap = ctrl.shared.snapshot()
    assert snap["user_wants_running"] is False
    assert "mss quebrou" in snap["error_message"]
    assert ctrl.releases, "teclas devem ser soltas ao cair no supervisor"
    # o erro nao pode ser apagado por um 'Parado' generico
    time.sleep(0.6)
    assert ctrl.shared.snapshot()["state"] == AppState.ERRO
    assert ctrl._thread.is_alive()


def test_perda_de_foco_para_o_bot_com_mensagem_clara(ctrl, monkeypatch):
    def lost(self):
        raise FocusLostError("x")
    monkeypatch.setattr(Controller, "_run_once", lost)

    ctrl.shared.update(user_wants_running=True)
    _start_thread(ctrl)

    assert _wait_for(lambda: ctrl.shared.snapshot()["state"] == AppState.ERRO)
    snap = ctrl.shared.snapshot()
    assert snap["user_wants_running"] is False
    assert "perdeu o foco" in snap["error_message"]


def test_depois_do_erro_iniciar_de_novo_roda_outra_vez(ctrl, monkeypatch):
    calls = []

    def flaky(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("primeira vez falha")
        self.shared.update(user_wants_running=False)  # segunda: roda e termina ok

    monkeypatch.setattr(Controller, "_run_once", flaky)
    ctrl.shared.update(user_wants_running=True)
    _start_thread(ctrl)
    assert _wait_for(lambda: ctrl.shared.snapshot()["state"] == AppState.ERRO)

    ctrl.shared.update(user_wants_running=True, error_message="")  # o que o botao INICIAR faz
    assert _wait_for(lambda: len(calls) == 2)
    assert _wait_for(lambda: ctrl.shared.snapshot()["state"] == AppState.PARADO)


# -- panico e shutdown -----------------------------------------------------------

def test_panico_para_o_bot_e_solta_tudo(ctrl):
    ctrl.shared.update(user_wants_running=True)
    ctrl.panic()
    snap = ctrl.shared.snapshot()
    assert snap["user_wants_running"] is False
    assert snap["state"] == AppState.ERRO
    assert "EMERGENCIA" in snap["error_message"]
    assert ctrl.shared.should_stop_cycle() is True
    assert ctrl.releases


def test_shutdown_espera_a_thread_e_solta_tudo(ctrl, monkeypatch):
    monkeypatch.setattr(Controller, "_run_once", lambda self: time.sleep(0.05))
    ctrl.shared.update(user_wants_running=True)
    _start_thread(ctrl)
    ctrl.shutdown(timeout=2.0)
    assert not ctrl._thread.is_alive()
    assert ctrl.releases
    assert ctrl.shared.snapshot()["quit_requested"] is True


# -- watchdog ----------------------------------------------------------------------

def test_saude_da_janela_ok_quando_nada_mudou():
    w = _window()
    assert check_window_health(w, still_valid=lambda _: True, refresh=lambda x: x) is None


def test_saude_da_janela_detecta_sumico():
    w = _window()
    assert "sumiu" in check_window_health(w, still_valid=lambda _: False, refresh=lambda x: x)
    assert "sumiu" in check_window_health(w, still_valid=lambda _: True, refresh=lambda _: None)


def test_saude_da_janela_detecta_mudanca_de_posicao_e_tamanho():
    w = _window()
    moved = _window(left=100)
    resized = _window(width=1280, height=720)
    assert "mudou" in check_window_health(w, still_valid=lambda _: True, refresh=lambda _: moved)
    assert "mudou" in check_window_health(w, still_valid=lambda _: True, refresh=lambda _: resized)


def test_watchdog_pede_aborto_do_ciclo_quando_a_janela_some():
    shared = SharedState()
    shared.update(user_wants_running=True)
    assert shared.should_stop_cycle() is False

    dog = _WindowWatchdog(shared, _window(), interval=0.02,
                          check=lambda w: "A janela do FiveM sumiu")
    dog.start()
    try:
        assert _wait_for(shared.should_stop_cycle)
    finally:
        dog.stop()
    assert shared.snapshot()["abort_reason"] == "A janela do FiveM sumiu"


def test_watchdog_com_erro_na_checagem_aborta_por_seguranca():
    shared = SharedState()
    shared.update(user_wants_running=True)

    def bad(_w):
        raise OSError("win32")

    dog = _WindowWatchdog(shared, _window(), interval=0.02, check=bad)
    dog.start()
    try:
        assert _wait_for(shared.should_stop_cycle)
    finally:
        dog.stop()


def test_clear_abort_libera_o_proximo_ciclo():
    shared = SharedState()
    shared.update(user_wants_running=True)
    shared.request_abort("motivo A")
    shared.request_abort("motivo B")           # o primeiro motivo vale
    assert shared.snapshot()["abort_reason"] == "motivo A"
    shared.clear_abort()
    assert shared.should_stop_cycle() is False


# -- espera de foco ------------------------------------------------------------

def test_espera_de_foco_estoura_com_focus_lost(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod, "FOCUS_WAIT_TIMEOUT", 0.2)
    monkeypatch.setattr(controller_mod, "is_foreground", lambda _h: False)
    monkeypatch.setattr(controller_mod, "bring_to_foreground", lambda _h: False)
    ctrl.shared.update(user_wants_running=True)
    with pytest.raises(FocusLostError):
        ctrl._wait_for_game_focus(_window())


def test_espera_de_foco_retorna_assim_que_o_jogo_ganha_foco(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod, "is_foreground", lambda _h: True)
    ctrl.shared.update(user_wants_running=True)
    assert ctrl._wait_for_game_focus(_window()) is True


def test_espera_de_foco_respeita_o_botao_parar(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod, "is_foreground", lambda _h: False)
    monkeypatch.setattr(controller_mod, "bring_to_foreground", lambda _h: False)
    ctrl.shared.update(user_wants_running=False)
    assert ctrl._wait_for_game_focus(_window()) is False
