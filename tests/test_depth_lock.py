"""run_depth_lock: quando a tecla de parar a profundidade (E) pode ou NAO pode ser apertada.

A tecla E faz outras coisas no jogo, entao os testes mais importantes sao os de
"nao aperta": sem o prompt na tela, sem leitura certa, com leitura suspeita...
O HUD e simulado por um roteiro (Scenario); o resto e o codigo de producao.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from fishingbot import fishing_logic as fl
from fishingbot.app_state import AppState, SharedState
from fishingbot.fishing_logic import DepthLock
from fishingbot.regions import Region
from fishingbot.stats import CastOutcome

KEYBINDS = {"stop_depth_key": "e", "space_key": "space", "use_item_key": "4", "pull_key": "s", "release_key": "w"}
REGIONS = {"hook_zone": Region(0, 0, 252, 108), "pulling_state": Region(0, 0, 270, 43),
           "depth_row": Region(0, 0, 270, 43)}


class Scenario:
    """Roteiro do HUD: cada passo e (prompt_visivel, profundidade_lida|None[, mordida])."""

    def __init__(self, steps, press_clears_prompt=True):
        self.steps = list(steps)
        self.i = -1
        self.taps: list[str] = []
        self.pressed = False
        self.press_clears_prompt = press_clears_prompt

    def _step(self):
        return self.steps[min(max(self.i, 0), len(self.steps) - 1)]

    def prompt(self, _frame):
        if self.pressed and self.press_clears_prompt:
            return False
        self.i += 1
        return bool(self._step()[0])

    def read(self, _frame):
        value = self._step()[1]
        return SimpleNamespace(value=value, reason="" if value is not None else "sem o 'm'", min_margin=0.1)

    def hook(self, *_a):
        step = self._step()
        return SimpleNamespace(ball=len(step) > 2 and bool(step[2]), bright_ratio=0.0, mask=None)

    def tap(self, key, hold_seconds=0.03):
        self.taps.append(key)
        self.pressed = True


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(fl, "DEPTH_POLL_SECONDS", 0.0)
    monkeypatch.setattr(fl, "DEPTH_PRESS_VERIFY_SECONDS", 0.3)
    monkeypatch.setattr(fl.vision, "grab", lambda *_a, **_k: np.zeros((43, 270, 3), np.uint8))

    def _run(scenario, target=5, dry_run=False, max_wait=1.0, shared=None):
        monkeypatch.setattr(fl.depth_reader, "depth_prompt_visible", scenario.prompt)
        monkeypatch.setattr(fl.depth_reader, "read_depth", scenario.read)
        monkeypatch.setattr(fl, "_read_hook", scenario.hook)
        monkeypatch.setattr(fl.input_sim, "tap", scenario.tap)
        shared = shared or SharedState()
        shared.update(user_wants_running=True)
        return fl.run_depth_lock(None, REGIONS, KEYBINDS, shared, dry_run, target, max_wait), shared

    return _run


def P(value, ball=False):
    """Passo com o prompt na tela e a profundidade lida."""
    return (True, value, ball)


# -- aperta quando deve ---------------------------------------------------------------------------------

def test_aperta_E_uma_vez_ao_chegar_no_alvo(run):
    sc = Scenario([P(0), P(1), P(2), P(3), P(4), P(5), P(5), P(6)])
    result, _ = run(sc, target=5)
    assert result is DepthLock.LOCKED
    assert sc.taps == ["e"]


def test_aguarda_o_prompt_aparecer_durante_o_arremesso(run):
    """Durante o ARREMESSANDO o prompt ainda nao existe: nao aperta nem desiste."""
    sc = Scenario([(False, None)] * 20 + [P(1), P(2), P(3), P(3)])
    result, _ = run(sc, target=3)
    assert result is DepthLock.LOCKED and sc.taps == ["e"]


def test_precisa_de_duas_leituras_seguidas_no_alvo(run):
    sc = Scenario([P(2), P(3), P(2), P(3), P(3)])         # 3, volta pra 2, 3, 3
    result, _ = run(sc, target=3)
    assert result is DepthLock.LOCKED and len(sc.taps) == 1
    assert sc.i >= 4, "so apertou depois da segunda leitura seguida (indice 4), nao na primeira"


def test_ja_passou_do_alvo_na_primeira_leitura_aperta_logo(run):
    sc = Scenario([P(9), P(9)])
    result, _ = run(sc, target=4)
    assert result is DepthLock.LOCKED and sc.taps == ["e"]


def test_usa_a_tecla_configurada(run, monkeypatch):
    sc = Scenario([P(5), P(5)])
    monkeypatch.setitem(KEYBINDS, "stop_depth_key", "r")
    try:
        run(sc, target=5)
    finally:
        KEYBINDS["stop_depth_key"] = "e"
    assert sc.taps == ["r"]


def test_dry_run_nao_envia_tecla(run):
    sc = Scenario([P(5), P(5)])
    result, _ = run(sc, target=5, dry_run=True)
    assert result is DepthLock.LOCKED and sc.taps == []


# -- NAO aperta ------------------------------------------------------------------------------------------

def test_nunca_aperta_sem_o_prompt_na_tela(run):
    """Mesmo com a profundidade 'lida' acima do alvo, sem o prompt nao ha E."""
    sc = Scenario([(False, 30)] * 50)
    result, _ = run(sc, target=5, max_wait=0.3)
    assert result is DepthLock.TIMEOUT and sc.taps == []


def test_prompt_some_antes_do_alvo_e_o_fundo_e_nao_aperta(run):
    sc = Scenario([P(1), P(2), P(3), (False, None)])
    result, _ = run(sc, target=20)
    assert result is DepthLock.BOTTOM and sc.taps == []


def test_leitura_ilegivel_nao_aperta_e_avisa(run, monkeypatch):
    monkeypatch.setattr(fl, "DEPTH_UNREADABLE_WARN_SECONDS", 0.05)
    sc = Scenario([P(None)] * 5000)
    result, shared = run(sc, target=5, max_wait=0.4)
    assert result is DepthLock.UNREADABLE and sc.taps == []
    assert "NAO foi travada" in shared.snapshot()["status_message"]


def test_leitura_isolada_alta_demais_nao_dispara(run):
    """Um pico de leitura (ex.: 25 no meio de 3,4,4) nao pode apertar E."""
    sc = Scenario([P(3), P(4), P(25), P(4), P(4), (False, None)])
    result, _ = run(sc, target=10)
    assert result is DepthLock.BOTTOM and sc.taps == []


def test_pico_e_depois_volta_ao_normal_nao_conta_como_confirmacao(run):
    sc = Scenario([P(9), P(30), P(9), P(10), P(10)])      # 30 e um pico; 10,10 e a confirmacao real
    result, _ = run(sc, target=10)
    assert result is DepthLock.LOCKED and len(sc.taps) == 1
    assert sc.i >= 4


def test_mordida_enquanto_afunda_tem_prioridade(run):
    sc = Scenario([P(1), P(2, ball=True), P(3, ball=True), P(9), P(9)])
    result, _ = run(sc, target=9)
    assert result is DepthLock.BITE and sc.taps == []


def test_parar_interrompe_sem_apertar(run):
    shared = SharedState()
    sc = Scenario([P(1)] * 5000)
    threading.Timer(0.1, lambda: shared.update(user_wants_running=False)).start()
    result, _ = run(sc, target=99, max_wait=5.0, shared=shared)
    assert result is DepthLock.STOPPED and sc.taps == []


# -- verificacao depois de apertar --------------------------------------------------------------------------

def test_se_o_prompt_continua_depois_do_E_tenta_de_novo_e_depois_desiste(run):
    sc = Scenario([P(5)] * 5000, press_clears_prompt=False)
    result, _ = run(sc, target=5, max_wait=3.0)
    assert result is DepthLock.FAILED
    assert sc.taps == ["e", "e"], "no maximo DEPTH_MAX_PRESSES apertos"


def test_pausa_nao_consome_o_tempo_da_trava(run):
    shared = SharedState()
    shared.update(user_wants_running=True)
    shared.set_pause("FiveM minimizado")
    threading.Timer(0.5, shared.clear_pause).start()
    sc = Scenario([P(5), P(5)])
    result, _ = run(sc, target=5, max_wait=0.3, shared=shared)    # a pausa dura mais que o prazo
    assert result is DepthLock.LOCKED and sc.taps == ["e"]


# -- integracao com o lance ----------------------------------------------------------------------------------

@pytest.fixture
def cast_env(monkeypatch):
    calls = []
    monkeypatch.setattr(fl, "run_start_sequence", lambda *a, **k: calls.append("lancou"))
    monkeypatch.setattr(fl, "wait_for_bite", lambda *a, **k: calls.append("mordida") or False)
    monkeypatch.setattr(fl, "run_depth_lock", lambda *a, **k: calls.append(("trava", a[5], a[6])) or DepthLock.LOCKED)
    timings = {"bite_timeout_seconds": 5, "cast_confirm_seconds": 45.0, "depth_lock_max_wait_seconds": 77}
    return calls, timings


def test_lance_sem_alvo_nao_mexe_na_profundidade(cast_env):
    calls, timings = cast_env
    shared = SharedState()
    shared.update(user_wants_running=True)
    out = fl.do_one_cast(None, REGIONS, KEYBINDS, timings, shared, dry_run=True)
    assert out is CastOutcome.NO_BITE
    assert calls == ["lancou", "mordida"], "sem alvo: comportamento de sempre"


def test_lance_com_alvo_trava_entre_o_lancamento_e_a_espera_da_mordida(cast_env):
    calls, timings = cast_env
    shared = SharedState()
    shared.update(user_wants_running=True)
    fl.do_one_cast(None, REGIONS, KEYBINDS, timings, shared, dry_run=True, depth_target=12)
    assert calls == ["lancou", ("trava", 12, 77), "mordida"]


def test_problema_ao_travar_nao_derruba_o_lance_mas_avisa(cast_env, monkeypatch):
    calls, timings = cast_env
    monkeypatch.setattr(fl, "run_depth_lock", lambda *a, **k: DepthLock.UNREADABLE)
    shared = SharedState()
    shared.update(user_wants_running=True)
    seen = []
    real = shared.set_state
    monkeypatch.setattr(shared, "set_state", lambda st, msg=None: (seen.append(msg), real(st, msg)))
    out = fl.do_one_cast(None, REGIONS, KEYBINDS, timings, shared, dry_run=True, depth_target=12)
    assert out is CastOutcome.NO_BITE                      # seguiu pra espera da mordida
    assert any(m and "NAO foi travada" in m for m in seen)
    assert shared.snapshot()["state"] in (AppState.AGUARDANDO_MINIGAME,)
