"""Disjuntor, backoff, monitor de saude e laco de automacao com falhas simuladas."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from mss.exception import ScreenShotError

from fishingbot import controller as controller_mod
from fishingbot import diagnostics, fishing_logic, manual_control
from fishingbot.app_state import AppState, SharedState
from fishingbot.controller import Controller, _HealthMonitor
from fishingbot.regions import Region, compute_all_regions
from fishingbot.stats import CastOutcome
from fishingbot.window_detect import WindowInfo

O = CastOutcome


def _window(**kw) -> WindowInfo:
    base = dict(hwnd=1, title="FiveM", process_name="FiveM_GTAProcess.exe",
                left=0, top=0, width=1280, height=720)
    base.update(kw)
    return WindowInfo(**base)


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(controller_mod.input_sim, "release_all", lambda: None)
    c = Controller(SharedState(), dry_run=True)
    c.cfg["safety"].update(max_consecutive_failures=3, retry_backoff_base_seconds=0.0,
                           retry_backoff_max_seconds=0.0)
    c.cfg["timings"]["after_confirm_delay_seconds"] = 0.0
    c.bundles = []
    monkeypatch.setattr(diagnostics, "save_bundle",
                        lambda *a, **k: c.bundles.append(a[0]) or "C:/diag/pasta")
    return c


# -- _handle_outcome: disjuntor -----------------------------------------------------

def test_disjuntor_desarma_na_n_esima_falha_seguida(ctrl):
    sh = ctrl.shared
    sh.update(user_wants_running=True)
    assert ctrl._handle_outcome(O.NO_BITE, None, _window(), {}) is True
    assert ctrl._handle_outcome(O.HIT_TIMEOUT, None, _window(), {}) is True
    assert ctrl._handle_outcome(O.NO_PANEL, None, _window(), {}) is False

    snap = sh.snapshot()
    assert snap["state"] == AppState.ERRO and snap["user_wants_running"] is False
    assert "3 lances seguidos falharam" in snap["error_message"]
    assert "sem mordida: 1" in snap["error_message"]
    assert ctrl.bundles, "deve salvar o pacote de diagnostico"
    assert ctrl.stats.consecutive_failures == 0, "novo INICIAR recomeca a contagem"


def test_captura_no_meio_zera_a_contagem(ctrl):
    ctrl.shared.update(user_wants_running=True)
    for o in (O.NO_BITE, O.NO_BITE, O.CAPTURED, O.NO_BITE, O.NO_BITE):
        assert ctrl._handle_outcome(o, None, _window(), {}) is True
    assert ctrl.shared.snapshot()["user_wants_running"] is True


def test_interrupcao_nao_conta_pro_disjuntor(ctrl):
    ctrl.shared.update(user_wants_running=True)
    for _ in range(10):
        assert ctrl._handle_outcome(O.STOPPED, None, _window(), {}) is True
    assert ctrl.stats.attempts == 0


def test_resumo_vai_pra_interface(ctrl):
    ctrl.shared.update(user_wants_running=True)
    ctrl._handle_outcome(O.CAPTURED, None, _window(), {})
    assert "Capturas: 1" in ctrl.shared.snapshot()["stats_text"]


def test_backoff_dobra_e_respeita_o_teto(ctrl):
    ctrl.cfg["safety"].update(retry_backoff_base_seconds=0.5, retry_backoff_max_seconds=3.0)
    got = []
    for _ in range(5):
        ctrl.stats.record(O.NO_BITE)
        got.append(ctrl._backoff_seconds())
    assert got == [0.5, 1.0, 2.0, 3.0, 3.0]


def test_config_maluco_nao_quebra_o_disjuntor(ctrl):
    ctrl.cfg["safety"]["max_consecutive_failures"] = "cinco"   # invalido -> default 5
    ctrl.shared.update(user_wants_running=True)
    for _ in range(4):
        assert ctrl._handle_outcome(O.NO_BITE, None, _window(), {}) is True
    assert ctrl._handle_outcome(O.NO_BITE, None, _window(), {}) is False


# -- laco de automacao completo, com do_one_cast simulado ----------------------------------

@pytest.fixture
def loop_env(ctrl, monkeypatch):
    """_automation_loop de verdade (mss real so pra monitors[0]); watchdog e
    monitor de saude desligados, e do_one_cast devolve uma sequencia."""
    monkeypatch.setattr(controller_mod._WindowWatchdog, "start", lambda self: None)
    monkeypatch.setattr(_HealthMonitor, "start", lambda self: None)
    win = _window()
    regions = compute_all_regions(win.left, win.top, win.width, win.height)

    def run(sequence):
        calls = []
        seq = iter(sequence)

        def fake_cast(*a, **k):
            calls.append(1)
            item = next(seq)
            if isinstance(item, Exception):
                raise item
            return item
        monkeypatch.setattr(fishing_logic, "do_one_cast", fake_cast)
        monkeypatch.setattr(manual_control, "wait_for_confirmation", lambda _abort: True)
        monkeypatch.setattr(controller_mod.time, "sleep", lambda _s: None)
        ctrl.shared.update(user_wants_running=True)
        ctrl._automation_loop(win, regions, ctrl.cfg["keybinds"], ctrl.cfg["timings"])
        return len(calls)
    return run


def test_laco_para_no_disjuntor_e_mostra_erro(ctrl, loop_env):
    n = loop_env([O.NO_BITE] * 10)
    assert n == 3
    snap = ctrl.shared.snapshot()
    assert snap["state"] == AppState.ERRO and "falharam" in snap["error_message"]


def test_laco_captura_reseta_contagem_e_espera_confirmacao(ctrl, loop_env):
    n = loop_env([O.NO_BITE, O.NO_BITE, O.CAPTURED, O.NO_BITE, O.NO_BITE, O.NO_BITE])
    assert n == 6                        # so o 3o NO_BITE *depois* da captura desarma
    assert ctrl.stats.captured == 1


def test_laco_erro_de_captura_conta_como_falha_e_recria_o_mss(ctrl, loop_env):
    n = loop_env([ScreenShotError("gdi falhou"), O.CAPTURED, O.NO_BITE, O.NO_BITE, O.NO_BITE])
    assert n == 5
    assert ctrl.stats.counts[O.CAPTURE_ERROR] == 1


def test_laco_recusa_regiao_fora_da_tela(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod._WindowWatchdog, "start", lambda self: None)
    monkeypatch.setattr(_HealthMonitor, "start", lambda self: None)
    regions = {"hook_zone": Region(50000, 50000, 100, 100)}
    called = []
    monkeypatch.setattr(fishing_logic, "do_one_cast", lambda *a, **k: called.append(1) or O.CAPTURED)
    ctrl.shared.update(user_wants_running=True)
    ctrl._automation_loop(_window(), regions, ctrl.cfg["keybinds"], ctrl.cfg["timings"])
    assert not called
    snap = ctrl.shared.snapshot()
    assert snap["state"] == AppState.ERRO and "fora da tela" in snap["error_message"]


# -- monitor de saude ---------------------------------------------------------------------------

@pytest.fixture
def health(ctrl):
    return _HealthMonitor(ctrl.shared, _window(), {}, ctrl.cfg)


def _snap(state=AppState.AGUARDANDO_MINIGAME, last_progress=0.0, pause=""):
    return {"state": state, "last_progress_at": last_progress, "stats_text": "",
            "pause_reason": pause}


def _wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _live(seed=0):
    return np.random.default_rng(seed).integers(20, 200, (36, 64), dtype=np.uint8)


def test_saude_ok_quando_ha_movimento_e_progresso_recente(health):
    now = controller_mod.time.monotonic()
    assert health.evaluate(_snap(last_progress=now - 30), _live(), now) is None


def test_saude_detecta_tela_preta(health):
    black = np.zeros((36, 64), np.uint8)
    t0 = controller_mod.time.monotonic()
    snap = _snap(last_progress=t0)
    assert health.evaluate(snap, black, t0) is None
    assert "PRETA" in health.evaluate(snap, black, t0 + 5)


def test_saude_detecta_falta_de_progresso(health):
    now = controller_mod.time.monotonic()
    msg = health.evaluate(_snap(last_progress=now - 20 * 60), _live(), now)
    assert msg and "Nenhum progresso" in msg


def test_saude_sem_progresso_registrado_ainda_nao_dispara(health):
    now = controller_mod.time.monotonic()
    assert health.evaluate(_snap(last_progress=0.0), _live(), now) is None


def test_saude_espera_manual_nao_e_travamento(health, ctrl):
    black = np.zeros((36, 64), np.uint8)
    now = controller_mod.time.monotonic()
    old = now - 3600                       # 1h esperando o ENTER do jogador
    assert health.evaluate(_snap(AppState.AGUARDANDO_CONFIRMACAO_MANUAL, old), black, now) is None
    assert ctrl.shared.snapshot()["last_progress_at"] >= now, "reinicia o relogio de progresso"


def test_saude_pausa_do_jogo_nao_e_tela_preta_nem_travamento(health, ctrl):
    black = np.zeros((36, 64), np.uint8)       # minimizado: a captura mostra o desktop
    now = controller_mod.time.monotonic()
    snap = _snap(last_progress=now - 3600, pause="FiveM minimizado")
    for i in range(10):
        assert health.evaluate(snap, black, now + i * 5) is None


# -- espera manual pendente (nao lanca a vara sem a confirmacao do jogador) ------------------

def test_laco_reiniciado_durante_a_espera_manual_volta_a_esperar(ctrl, loop_env, monkeypatch):
    waits = []

    def fake_wait(_abort):
        waits.append(1)
        return len(waits) > 1          # 1a vez: interrompido (laco reinicia); 2a: confirma

    casts = []
    seq = iter([O.CAPTURED, O.NO_BITE, O.NO_BITE, O.NO_BITE])

    def run_loop():
        monkeypatch.setattr(fishing_logic, "do_one_cast", lambda *a, **k: casts.append(1) or next(seq))
        monkeypatch.setattr(manual_control, "wait_for_confirmation", fake_wait)
        monkeypatch.setattr(controller_mod.time, "sleep", lambda _s: None)
        win = _window()
        regions = compute_all_regions(win.left, win.top, win.width, win.height)
        ctrl.shared.update(user_wants_running=True)
        ctrl._automation_loop(win, regions, ctrl.cfg["keybinds"], ctrl.cfg["timings"])

    run_loop()                           # captura -> espera -> "interrompido" -> sai
    assert ctrl._pending_manual is True and len(casts) == 1
    ctrl.shared.clear_abort()
    run_loop()                           # reinicio: tem que ESPERAR antes de lancar
    assert waits == [1, 1], "esperou de novo em vez de lancar a vara"
    assert ctrl._pending_manual is False
    assert len(casts) == 1 + 3, "so lancou depois da confirmacao"


def test_parar_cancela_a_espera_pendente(ctrl, monkeypatch):
    ctrl._pending_manual = True
    monkeypatch.setattr(Controller, "_run_once", lambda self: None)
    ctrl.shared.update(user_wants_running=False)
    t = threading.Thread(target=ctrl._run, daemon=True)
    t.start()
    assert _wait_for(lambda: ctrl._pending_manual is False)
    ctrl.request_quit()
    t.join(timeout=2)


# -- fases pausam em vez de falhar quando o jogo some de vista ---------------------------------

class _NoScreen:
    def grab(self, *_a, **_k):
        raise AssertionError("nao pode capturar a tela enquanto pausado")


def test_wait_for_bite_pausado_acorda_e_para_se_mandarem_parar():
    shared = SharedState()
    shared.update(user_wants_running=True)
    shared.set_pause("FiveM minimizado")
    threading.Timer(0.2, lambda: shared.update(user_wants_running=False)).start()
    assert fishing_logic.wait_for_bite(_NoScreen(), {"hook_zone": Region(0, 0, 10, 10)},
                                       shared, True, 30.0, 45.0) is False


# -- pausa de uma execucao anterior NAO pode travar o proximo INICIAR ----------------------------
# Relato: "nao esta lancando a linha". No log, os 7 reinicios feitos com uma pausa ainda aberta
# (jogo fora de foco -> PARAR -> INICIAR) nunca apertaram o 4; os 29 sem pausa pendente apertaram
# todos. A pausa so era liberada pelo watchdog ao ver o jogo voltar; PARAR/INICIAR deixava
# pause_reason gravado e o checkpoint() do primeiro lancamento ficava bloqueado.

def test_iniciar_depois_de_uma_pausa_antiga_lanca_a_vara(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod._WindowWatchdog, "start", lambda self: None)
    monkeypatch.setattr(_HealthMonitor, "start", lambda self: None)
    win = _window()
    monkeypatch.setattr(ctrl, "_find_window_blocking", lambda: win)
    monkeypatch.setattr(ctrl, "_calibrate", lambda w: (compute_all_regions(0, 0, win.width, win.height),
                                                        ctrl.cfg["keybinds"], ctrl.cfg["timings"]))
    lancou = []

    def fake_start(*a, **k):
        lancou.append(1)
        ctrl.shared.update(user_wants_running=False)      # basta ver que lancou; encerra o laco
    monkeypatch.setattr(fishing_logic, "run_start_sequence", fake_start)
    monkeypatch.setattr(fishing_logic, "wait_for_bite", lambda *a, **k: False)

    # execucao anterior terminou com o jogo fora de foco (pausa aberta) e o usuario apertou PARAR
    ctrl.shared.set_pause("FiveM sem foco (em primeiro plano: Alternancia de Tarefas [explorer.exe])")
    ctrl.shared.update(user_wants_running=True)             # ...e depois INICIAR

    t = threading.Thread(target=ctrl._run_once, daemon=True)
    t.start()
    assert _wait_for(lambda: lancou, timeout=2.0), "a pausa velha bloqueou o primeiro lancamento"
    t.join(timeout=3)


def test_parar_nao_deixa_a_pausa_gravada(ctrl, loop_env):
    ctrl.shared.set_pause("FiveM sem foco")
    loop_env([O.NO_BITE] * 10)                  # roda o laco ate o disjuntor parar o bot
    assert ctrl.shared.snapshot()["pause_reason"] == ""


def test_gui_nao_mostra_pausado_depois_de_parar(ctrl, loop_env):
    """pause_reason velho faria a interface mostrar 'PAUSADO' com o bot parado."""
    ctrl.shared.set_pause("FiveM minimizado")
    loop_env([O.NO_BITE] * 10)
    assert not ctrl.shared.snapshot()["pause_reason"]
