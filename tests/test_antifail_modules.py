"""stats, capture_health, diagnostics, config.number e manual_control.confirm."""
from __future__ import annotations

import logging

import numpy as np
import pytest

from fishingbot import config_store, diagnostics, manual_control
from fishingbot.capture_health import CaptureMonitor, validate_regions
from fishingbot.regions import Region
from fishingbot.stats import CastOutcome, SessionStats

O = CastOutcome


# -- stats -----------------------------------------------------------------------

def test_falhas_seguidas_zeram_com_uma_captura():
    s = SessionStats()
    for o in (O.NO_BITE, O.HIT_TIMEOUT, O.NO_PANEL):
        s.record(o)
    assert s.consecutive_failures == 3
    s.record(O.CAPTURED)
    assert s.consecutive_failures == 0
    assert (s.attempts, s.captured) == (4, 1)


def test_interrupcao_nao_conta_nem_como_falha_nem_como_sucesso():
    s = SessionStats()
    s.record(O.NO_BITE)
    s.record(O.STOPPED)
    assert s.attempts == 1 and s.consecutive_failures == 1


def test_resumo_e_detalhe_das_falhas():
    s = SessionStats()
    assert s.summary() == "Lances: 0"
    for o in (O.NO_BITE, O.NO_BITE, O.CAPTURED, O.NO_PANEL):
        s.record(o)
    assert "Lances: 4" in s.summary() and "Capturas: 1 (25%)" in s.summary()
    assert "Falhas seguidas: 1" in s.summary()
    assert s.breakdown().startswith("sem mordida: 2")
    assert "capturado" not in s.breakdown()


# -- saude da captura ---------------------------------------------------------------

def _scene(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(20, 200, (36, 64), dtype=np.uint8)


def test_tela_preta_so_dispara_depois_do_tempo():
    m = CaptureMonitor(black_seconds=3.0)
    black = np.zeros((36, 64), np.uint8)
    assert m.update(black, 0.0) is None
    assert m.update(black, 2.9) is None
    assert "PRETA" in m.update(black, 3.0)


def test_tela_preta_curta_e_ignorada():
    m = CaptureMonitor(black_seconds=3.0)
    black = np.zeros((36, 64), np.uint8)
    assert m.update(black, 0.0) is None
    assert m.update(_scene(1), 1.0) is None       # voltou imagem: zera a contagem
    assert m.update(black, 2.0) is None
    assert m.update(black, 4.5) is None           # so 2.5s seguidos desde 2.0


def test_imagem_congelada_dispara_mas_cena_com_movimento_nao():
    m = CaptureMonitor(frozen_seconds=15.0)
    frozen = _scene(7)
    assert m.update(frozen, 0.0) is None
    assert m.update(frozen.copy(), 14.0) is None
    assert "CONGELADA" in m.update(frozen.copy(), 15.5)

    m2 = CaptureMonitor(frozen_seconds=15.0)
    for t in range(0, 60):
        assert m2.update(_scene(t), float(t)) is None  # agua/personagem se mexendo


def test_reset_limpa_as_contagens():
    m = CaptureMonitor(black_seconds=3.0)
    black = np.zeros((36, 64), np.uint8)
    m.update(black, 0.0)
    m.reset()
    assert m.update(black, 10.0) is None


def test_regioes_dentro_e_fora_da_tela():
    bounds = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    ok = {"a": Region(0, 0, 100, 100), "b": Region(1820, 980, 100, 100)}
    assert validate_regions(ok, bounds) == []
    fora = {"a": Region(1850, 980, 100, 100), "b": Region(-5, 10, 50, 50)}
    problemas = validate_regions(fora, bounds)
    assert len(problemas) == 2 and "'a'" in problemas[0]


def test_regioes_em_monitor_com_origem_negativa():
    bounds = {"left": -1920, "top": 0, "width": 3840, "height": 1080}   # 2 monitores
    assert validate_regions({"a": Region(-1900, 100, 200, 100)}, bounds) == []


# -- config ---------------------------------------------------------------------------------


def test_defaults_tem_secao_safety_e_config_antigo_recebe(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / config_store.APP_NAME
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"timings": {"bite_timeout_seconds": 10}}))
    cfg = config_store.load_config()
    assert cfg["safety"]["max_consecutive_failures"] == 5
    assert cfg["timings"]["after_confirm_delay_seconds"] == 1.5
    assert cfg["timings"]["bite_timeout_seconds"] == 10


# -- manual_control.confirm ---------------------------------------------------------------

def test_botao_continuar_so_vale_enquanto_espera():
    manual_control.disarm()
    assert manual_control.confirm() is False
    manual_control.arm()
    try:
        assert manual_control.confirm() is True
        assert manual_control._confirmed.is_set()
    finally:
        manual_control.disarm()


# -- diagnostics -------------------------------------------------------------------------------

class _Win:
    width, height, left, top = 320, 180, 0, 0


class _FakeSct:
    def grab(self, rect):
        return np.full((rect["height"], rect["width"], 4), 90, np.uint8)


@pytest.fixture
def diag_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    diagnostics.ring.lines.clear()
    return tmp_path


def test_pacote_de_diagnostico_tem_tudo(diag_env):
    diagnostics.install_ring_handler()
    logging.getLogger("fishingbot").warning("linha de teste do ring")
    regions = {"hook_zone": Region(10, 10, 50, 20), "pulling_state": Region(0, 0, 40, 10)}
    folder = diagnostics.save_bundle("5 lances seguidos falharam", _FakeSct(), _Win(), regions,
                                     "Lances: 5", {"keybinds": {"pull_key": "s"}, "timings": {}})
    assert folder is not None
    names = {p.name for p in folder.iterdir()}
    assert {"motivo.txt", "log_recente.txt", "janela.png",
            "regiao_hook_zone.png", "regiao_pulling_state.png"} <= names
    assert "5 lances seguidos" in (folder / "motivo.txt").read_text(encoding="utf-8")
    assert "linha de teste do ring" in (folder / "log_recente.txt").read_text(encoding="utf-8")


def test_diagnostico_nunca_levanta_excecao(diag_env):
    class Broken:
        def grab(self, rect):
            raise RuntimeError("sem tela")
    folder = diagnostics.save_bundle("x", Broken(), _Win(), {"r": Region(0, 0, 5, 5)}, "", {})
    assert folder is not None  # salvou o texto mesmo sem conseguir as imagens


def test_diagnostico_mantem_so_os_ultimos(diag_env, monkeypatch):
    base = diagnostics.diagnostics_dir()
    base.mkdir(parents=True)
    for i in range(diagnostics.MAX_BUNDLES + 4):
        (base / f"2026010{i:02d}_000000").mkdir()
    diagnostics._prune(base)
    assert len(list(base.iterdir())) == diagnostics.MAX_BUNDLES
