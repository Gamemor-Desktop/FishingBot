"""Fases do lance: pausa nao gasta timeout; puxada nao termina cedo demais."""
from __future__ import annotations

import threading
import time

from fishingbot import fishing_logic
from fishingbot.app_state import SharedState
from fishingbot.regions import Region
from fishingbot.stats import CastOutcome

KEYBINDS = {"pull_key": "s", "release_key": "w", "space_key": "space", "use_item_key": "4"}
REGIONS = {"hook_zone": Region(0, 0, 252, 108), "pulling_state": Region(0, 0, 270, 43)}


def _shared() -> SharedState:
    s = SharedState()
    s.update(user_wants_running=True)
    return s


def test_pausa_nao_consome_o_timeout_da_mordida(make_sct):
    """Timeout de 0.6s, jogo 'minimizado' por 1.0s: sem empurrar o prazo, o
    lance falharia (NO_BITE) assim que o jogo voltasse."""
    shared = _shared()
    shared.set_pause("FiveM minimizado")
    threading.Timer(1.0, shared.clear_pause).start()
    sct = make_sct("hook_zone", "010829")           # bolinha presente
    assert fishing_logic.wait_for_bite(sct, REGIONS, shared, True, 0.6, 45.0) is True


def test_sem_pausa_o_mesmo_timeout_estoura(make_sct):
    """Contraprova: sem bolinha, o timeout de 0.3s estoura normalmente."""
    sct = make_sct("hook_zone", "010809")           # cena vazia
    assert fishing_logic.wait_for_bite(sct, REGIONS, _shared(), True, 0.3, 45.0) is False


def _pull(monkeypatch, states, **kw):
    """Roda run_pulling_phase em dry-run com o classificador devolvendo `states`
    (e depois None pra sempre -- o painel 'sumiu')."""
    seq = iter(states)
    monkeypatch.setattr(fishing_logic, "classify_pull_state", lambda *_: next(seq, None))
    t0 = time.monotonic()
    outcome = fishing_logic.run_pulling_phase(
        None, REGIONS, KEYBINDS, _shared(), True, timeout_seconds=10,
        end_confirm_seconds=0.1, first_appear_timeout_seconds=1.0, **kw)
    return outcome, time.monotonic() - t0


def test_puxada_curta_demais_nao_vira_captura(monkeypatch):
    """Em log real, 'capturas' de 0-5s depois do ESPACO eram leituras erradas
    do painel. Com tempo minimo de 0.8s, o painel 'sumir' aos 0.1s nao encerra."""
    outcome, elapsed = _pull(monkeypatch, ["red"] * 3, min_pull_seconds=0.8)
    assert outcome is CastOutcome.CAPTURED
    assert elapsed >= 0.8


def test_sem_tempo_minimo_encerra_logo_depois_do_sumico(monkeypatch):
    outcome, elapsed = _pull(monkeypatch, ["red"] * 3, min_pull_seconds=0.0)
    assert outcome is CastOutcome.CAPTURED
    assert elapsed < 0.6


def test_painel_que_volta_durante_o_tempo_minimo_continua_puxando(monkeypatch):
    # painel some por um instante (leitura ruim), volta, e so some de vez no fim
    states = ["red"] * 3 + [None] * 3 + ["gray"] * 60
    outcome, elapsed = _pull(monkeypatch, states, min_pull_seconds=0.3)
    assert outcome is CastOutcome.CAPTURED
    assert elapsed > 1.0, "nao pode ter encerrado no primeiro sumico"
