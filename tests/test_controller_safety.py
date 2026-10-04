"""Controlador: supervisor, watchdog, panico, shutdown e estado de erro."""
from __future__ import annotations

import threading
import time

import pytest

from fishingbot import controller as controller_mod
from fishingbot import input_sim
from fishingbot.app_state import AppState, SharedState
from fishingbot.controller import Controller, WindowAssessor, _WindowWatchdog
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


# -- avaliacao da janela ---------------------------------------------------------------

def _assessor(window=None, require_focus=True, **probes):
    base = dict(exists=lambda: True, minimized=lambda: False, foreground=lambda: True,
                rect=lambda: (0, 0, 1920, 1080))
    base.update(probes)
    return WindowAssessor(window or _window(width=1920, height=1080), require_focus=require_focus, **base)


def test_janela_igual_esta_ok():
    assert _assessor().assess() == ("ok", "")


def test_janela_que_deixou_de_existir_aborta():
    action, reason = _assessor(exists=lambda: False).assess()
    assert action == "abort" and "sumiu" in reason


def test_minimizada_pausa_em_vez_de_abortar():
    """O FiveM se minimiza sozinho ao perder o foco: isso NAO e janela sumida."""
    assert _assessor(minimized=lambda: True).assess() == ("pause", "FiveM minimizado")


def test_sem_foco_pausa_so_quando_exige_foco():
    assert _assessor(foreground=lambda: False).assess() == ("pause", "FiveM sem foco")
    assert _assessor(require_focus=False, foreground=lambda: False).assess() == ("ok", "")


def test_tamanho_transitorio_da_restauracao_nao_aborta():
    """Restaurar da barra de tarefas passa por 1904x1042 -> 1920x1081 -> 1920x1080."""
    seq = iter([(0, 0, 1904, 1042), (0, 0, 1920, 1081), (0, 0, 1920, 1080), (0, 0, 1920, 1080)])
    a = _assessor(rect=lambda: next(seq))
    assert a.assess()[0] == "pause"
    assert a.assess()[0] == "pause"
    assert a.assess()[0] == "pause"   # 1080 ainda e diferente da leitura anterior (1081)
    assert a.assess() == ("ok", "")   # estabilizou, igual a calibrada


def test_um_pixel_de_diferenca_estavel_nao_recalibra():
    a = _assessor(rect=lambda: (0, 0, 1920, 1081))
    a.assess()                         # primeira leitura diferente da inicial: ajustando
    assert a.assess() == ("ok", "")    # estavel dentro da tolerancia de 4px


def test_mudanca_de_verdade_e_estavel_aborta_pra_recalibrar():
    a = _assessor(rect=lambda: (0, 0, 1280, 720))
    assert a.assess()[0] == "pause"
    action, reason = a.assess()
    assert action == "abort" and "mudou" in reason


def test_janela_deslocada_pra_outro_monitor_aborta():
    a = _assessor(rect=lambda: (1920, 0, 1920, 1080))
    a.assess()
    assert a.assess()[0] == "abort"


# -- watchdog ------------------------------------------------------------------------------

class _ScriptedAssessor:
    """Devolve a sequencia de avaliacoes e repete a ultima."""
    def __init__(self, *seq):
        self._seq = list(seq)

    def assess(self):
        return self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]


def _dog(shared, assessor, **kw):
    return _WindowWatchdog(shared, _window(), interval=0.01, assessor=assessor, **kw)


def test_watchdog_pede_aborto_quando_a_janela_some():
    shared = SharedState()
    shared.update(user_wants_running=True)
    dog = _dog(shared, _ScriptedAssessor(("abort", "A janela do FiveM sumiu")))
    dog.start()
    try:
        assert _wait_for(shared.should_stop_cycle)
    finally:
        dog.stop()
    assert shared.snapshot()["abort_reason"] == "A janela do FiveM sumiu"


def test_watchdog_com_erro_na_checagem_aborta_por_seguranca():
    shared = SharedState()
    shared.update(user_wants_running=True)

    class Bad:
        def assess(self):
            raise OSError("win32")

    dog = _dog(shared, Bad())
    dog.start()
    try:
        assert _wait_for(shared.should_stop_cycle)
    finally:
        dog.stop()


def test_minimizar_pausa_solta_teclas_e_voltar_retoma_sem_abortar(monkeypatch):
    released = []
    monkeypatch.setattr(controller_mod.input_sim, "release_all", lambda: released.append(1))
    shared = SharedState()
    shared.update(user_wants_running=True)
    dog = _dog(shared, _ScriptedAssessor(("pause", "FiveM minimizado"), ("pause", "FiveM minimizado"),
                                         ("ok", "")))
    dog.start()
    try:
        assert _wait_for(lambda: shared.snapshot()["pause_reason"] == "FiveM minimizado")
        assert released, "teclas seguradas devem ser soltas ao pausar"
        assert _wait_for(lambda: shared.snapshot()["pause_reason"] == "")
    finally:
        dog.stop()
    assert shared.should_stop_cycle() is False, "pausar nao cancela o lance"


def test_watchdog_para_o_bot_se_a_pausa_passar_do_limite(monkeypatch):
    monkeypatch.setattr(controller_mod.input_sim, "release_all", lambda: None)
    shared = SharedState()
    shared.update(user_wants_running=True)
    dog = _dog(shared, _ScriptedAssessor(("pause", "FiveM sem foco")), pause_timeout=0.05)
    dog.start()
    try:
        assert _wait_for(lambda: shared.snapshot()["state"] == AppState.ERRO)
    finally:
        dog.stop()
    snap = shared.snapshot()
    assert snap["user_wants_running"] is False and "FiveM sem foco" in snap["error_message"]


def test_durante_a_espera_manual_o_jogador_pode_sair_do_jogo(monkeypatch):
    monkeypatch.setattr(controller_mod.input_sim, "release_all", lambda: None)
    shared = SharedState()
    shared.update(user_wants_running=True)
    shared.set_state(AppState.AGUARDANDO_CONFIRMACAO_MANUAL)
    dog = _dog(shared, _ScriptedAssessor(("pause", "FiveM minimizado")))
    dog.start()
    time.sleep(0.2)
    dog.stop()
    assert shared.snapshot()["pause_reason"] == ""
    assert shared.should_stop_cycle() is False


def test_checkpoint_bloqueia_enquanto_pausado_e_devolve_o_tempo_parado():
    shared = SharedState()
    shared.update(user_wants_running=True)
    assert shared.checkpoint() == 0.0
    shared.set_pause("FiveM minimizado")
    threading.Timer(0.3, shared.clear_pause).start()
    waited = shared.checkpoint()
    assert 0.25 <= waited < 1.0


def test_checkpoint_acorda_se_mandarem_parar():
    shared = SharedState()
    shared.update(user_wants_running=True)
    shared.set_pause("FiveM minimizado")
    threading.Timer(0.2, lambda: shared.update(user_wants_running=False)).start()
    shared.checkpoint()  # nao pode ficar preso
    assert shared.should_stop_cycle() is True


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
