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


# -- fim da puxada com leitura INTERMITENTE do painel (falso "peixe capturado") -----------------
# Pesca real de 04/10/2026: puxada "concluida" em ~8-10 s, exatamente no tempo minimo, enquanto
# deveria durar bem mais. A regra antiga so zerava a contagem de "painel sumiu" com 3 leituras
# seguidas iguais; um classificador que erra 1 de cada 3 quadros COM O PAINEL NA TELA nunca
# confirmava e a puxada acabava assim que o tempo minimo passava.

import itertools  # noqa: E402

import pytest  # noqa: E402


def _flicker(monkeypatch, pattern, timeout=1.6, end_confirm=0.3, min_pull=0.3):
    seq = itertools.cycle(pattern)
    monkeypatch.setattr(fishing_logic, "classify_pull_state", lambda *_: next(seq))
    t0 = time.monotonic()
    outcome = fishing_logic.run_pulling_phase(
        None, REGIONS, KEYBINDS, _shared(), True, timeout_seconds=timeout,
        end_confirm_seconds=end_confirm, first_appear_timeout_seconds=1.0, min_pull_seconds=min_pull)
    return outcome, time.monotonic() - t0


@pytest.mark.parametrize("pattern", [
    ["gray", "gray", "gray", None],      # falha 25%
    ["gray", "gray", None],              # falha 33% (a que enganava a regra antiga)
    ["gray", None],                      # falha 50%
    ["gray", "red", None],               # alterna estados e falha
    [None, "gray", None, "gray", "gray"],
], ids=["25pct", "33pct", "50pct", "alterna", "irregular"])
def test_painel_na_tela_com_leitura_intermitente_nao_vira_captura(monkeypatch, pattern):
    outcome, elapsed = _flicker(monkeypatch, pattern)
    assert outcome is CastOutcome.PULL_TIMEOUT, "o painel esta na tela: nao pode ser 'capturado'"
    assert elapsed >= 1.5


def test_painel_que_some_de_vez_termina(monkeypatch):
    outcome, elapsed = _flicker(monkeypatch, ["gray"] * 20 + [None] * 100000, timeout=5.0)
    assert outcome is CastOutcome.CAPTURED
    assert elapsed < 2.0


def test_fade_out_com_leituras_falsas_esporadicas_termina(monkeypatch):
    """Painel sumiu, mas 1 em cada 13 quadros bate por coincidencia (<10%): termina."""
    outcome, _ = _flicker(monkeypatch, ["gray"] * 20 + ([None] * 12 + ["gray"]) * 100000, timeout=5.0)
    assert outcome is CastOutcome.CAPTURED


def test_respeita_o_tempo_minimo_mesmo_com_o_painel_ausente(monkeypatch):
    outcome, elapsed = _flicker(monkeypatch, ["gray"] * 3 + [None] * 100000, timeout=5.0,
                                end_confirm=0.2, min_pull=1.0)
    assert outcome is CastOutcome.CAPTURED and elapsed >= 1.0


def test_pausa_nao_conta_como_painel_ausente(monkeypatch):
    """Durante uma pausa a janela e limpa: voltar nao pode herdar 'quadros sem painel'."""
    shared = _shared()
    seq = itertools.chain(["gray"] * 10, itertools.repeat("gray"))
    monkeypatch.setattr(fishing_logic, "classify_pull_state", lambda *_: next(seq))
    shared.set_pause("FiveM minimizado")
    threading.Timer(0.4, shared.clear_pause).start()
    outcome = fishing_logic.run_pulling_phase(
        None, REGIONS, KEYBINDS, shared, True, timeout_seconds=1.2, end_confirm_seconds=0.2,
        first_appear_timeout_seconds=1.0, min_pull_seconds=0.0)
    assert outcome is CastOutcome.PULL_TIMEOUT


def test_fim_da_puxada_registra_a_estabilidade_da_leitura(monkeypatch, caplog):
    """Se muitos quadros ficaram sem painel ANTES do fim, o log avisa -- e e assim que um
    falso 'capturado' passa a deixar rastro."""
    pattern = (["gray"] * 3 + [None]) * 30 + [None] * 100000        # 25% de falha (~120 quadros), depois some de vez
    # 25% < 90%: a janela nunca atinge o limiar durante a parte instavel; so ao sumir de vez
    with caplog.at_level("INFO", logger="fishingbot"):
        outcome, _ = _flicker(monkeypatch, pattern, timeout=10.0, end_confirm=0.3, min_pull=0.2)
    assert outcome is CastOutcome.CAPTURED
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "Painel de pesca sumiu" in texto and "quadros" in texto
    assert "INSTAVEL" in texto
