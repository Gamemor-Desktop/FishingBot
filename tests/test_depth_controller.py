"""Opcao 'travar a profundidade': config, controlador e aviso de resolucao."""
from __future__ import annotations

import json

import pytest

from fishingbot import config_store as cs
from fishingbot import controller as controller_mod
from fishingbot import fishing_logic
from fishingbot.app_state import SharedState
from fishingbot.controller import Controller, _HealthMonitor
from fishingbot.regions import compute_all_regions
from fishingbot.stats import CastOutcome
from fishingbot.window_detect import WindowInfo


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(controller_mod.input_sim, "release_all", lambda: None)
    c = Controller(SharedState(), dry_run=True)
    c.cfg["safety"].update(max_consecutive_failures=2, retry_backoff_base_seconds=0.0, retry_backoff_max_seconds=0.0)
    return c


def _on_disk(tmp_path) -> dict:
    return json.loads((tmp_path / cs.APP_NAME / "config.json").read_text(encoding="utf-8"))


# -- config -------------------------------------------------------------------------------------------------

def test_padrao_e_desligado_com_tecla_e():
    assert cs.DEFAULTS["fishing"]["target_depth_m"] is None
    assert cs.DEFAULTS["keybinds"]["stop_depth_key"] == "e"


@pytest.mark.parametrize("ok", [1, 4, 25, 181, 500])
def test_profundidade_valida_passa(tmp_path, monkeypatch, ok):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / cs.APP_NAME
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"config_version": 2, "fishing": {"target_depth_m": ok}}))
    cfg, warnings = cs.load_config_with_report()
    assert cfg["fishing"]["target_depth_m"] == ok and warnings == []


@pytest.mark.parametrize("ruim", [0, -5, 501, 2.5, "dez", True, [3]])
def test_profundidade_invalida_desliga_com_aviso(tmp_path, monkeypatch, ruim):
    """Valor ruim nunca pode virar 'travar em qualquer profundidade': volta a desligado."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / cs.APP_NAME
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"config_version": 2, "fishing": {"target_depth_m": ruim}}))
    cfg, warnings = cs.load_config_with_report()
    assert cfg["fishing"]["target_depth_m"] is None
    assert any("target_depth_m" in w for w in warnings)


def test_tempo_maximo_e_tecla_sao_validados(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / cs.APP_NAME
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"config_version": 2, "keybinds": {"stop_depth_key": ""},
                                                "timings": {"depth_lock_max_wait_seconds": -1}}))
    cfg, warnings = cs.load_config_with_report()
    assert cfg["keybinds"]["stop_depth_key"] == "e"
    assert cfg["timings"]["depth_lock_max_wait_seconds"] == cs.DEFAULTS["timings"]["depth_lock_max_wait_seconds"]
    assert len(warnings) == 2


# -- Controller.set_target_depth ------------------------------------------------------------------------------

def test_set_target_depth_valido_vale_e_persiste(ctrl, tmp_path):
    assert ctrl.set_target_depth(12) is True
    assert cs.value(ctrl.cfg, "fishing", "target_depth_m") == 12
    assert _on_disk(tmp_path)["fishing"] == {"target_depth_m": 12}


def test_set_target_depth_invalido_nao_muda_nada(ctrl, tmp_path):
    ctrl.set_target_depth(8)
    for ruim in (0, -1, 999, "abc", 3.5, True):
        assert ctrl.set_target_depth(ruim) is False
    assert ctrl.cfg["fishing"]["target_depth_m"] == 8
    assert _on_disk(tmp_path)["fishing"] == {"target_depth_m": 8}


def test_desligar_volta_ao_padrao_e_sai_do_arquivo(ctrl, tmp_path):
    ctrl.set_target_depth(8)
    assert ctrl.set_target_depth(None) is True
    assert "fishing" not in _on_disk(tmp_path)


def test_valor_igual_nao_regrava_o_arquivo(ctrl, monkeypatch):
    ctrl.set_target_depth(8)
    gravacoes = []
    monkeypatch.setattr(cs, "save_config", lambda c: gravacoes.append(1))
    ctrl.set_target_depth(8)
    ctrl.set_target_depth(8)
    assert gravacoes == []


def test_falha_ao_gravar_nao_derruba_e_vale_na_sessao(ctrl, monkeypatch):
    monkeypatch.setattr(cs, "save_config", lambda c: (_ for _ in ()).throw(OSError("em uso")))
    assert ctrl.set_target_depth(15) is True
    assert ctrl.cfg["fishing"]["target_depth_m"] == 15


# -- o laco repassa o alvo ao lance -----------------------------------------------------------------------------

@pytest.fixture
def loop(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod._WindowWatchdog, "start", lambda self: None)
    monkeypatch.setattr(_HealthMonitor, "start", lambda self: None)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda _s: None)

    def run(window_size=(1920, 1080)):
        win = WindowInfo(hwnd=1, title="FiveM", process_name="x", left=0, top=0,
                         width=window_size[0], height=window_size[1])
        regions = compute_all_regions(0, 0, *window_size)
        seen = []

        def fake_cast(*a, **k):
            seen.append(k.get("depth_target", "AUSENTE"))
            return CastOutcome.NO_BITE
        monkeypatch.setattr(fishing_logic, "do_one_cast", fake_cast)
        ctrl.shared.update(user_wants_running=True)
        ctrl._automation_loop(win, regions, ctrl.cfg["keybinds"], ctrl.cfg["timings"])
        return seen
    return run


def test_laco_repassa_o_alvo_configurado(ctrl, loop):
    ctrl.set_target_depth(14)
    assert set(loop()) == {14}


def test_laco_sem_alvo_passa_none(ctrl, loop):
    assert set(loop()) == {None}


def test_mudar_o_alvo_vale_no_proximo_lance_sem_reiniciar(ctrl, monkeypatch):
    monkeypatch.setattr(controller_mod._WindowWatchdog, "start", lambda self: None)
    monkeypatch.setattr(_HealthMonitor, "start", lambda self: None)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda _s: None)
    ctrl.cfg["safety"]["max_consecutive_failures"] = 4
    seen = []

    def fake_cast(*a, **k):
        seen.append(k["depth_target"])
        if len(seen) == 2:
            ctrl.set_target_depth(30)        # o usuario muda o campo no meio da sessao
        return CastOutcome.NO_BITE
    monkeypatch.setattr(fishing_logic, "do_one_cast", fake_cast)
    ctrl.set_target_depth(10)
    win = WindowInfo(hwnd=1, title="FiveM", process_name="x", left=0, top=0, width=1920, height=1080)
    ctrl.shared.update(user_wants_running=True)
    ctrl._automation_loop(win, compute_all_regions(0, 0, 1920, 1080), ctrl.cfg["keybinds"], ctrl.cfg["timings"])
    assert seen == [10, 10, 30, 30]


def test_resolucao_menor_que_1080p_avisa_que_a_leitura_nao_foi_validada(ctrl, loop):
    ctrl.set_target_depth(10)
    loop(window_size=(1280, 720))
    notice = ctrl.shared.snapshot()["config_notice"]
    assert "1920x1080" in notice and "1280x720" in notice


def test_em_1080p_nao_ha_aviso_de_resolucao(ctrl, loop):
    ctrl.set_target_depth(10)
    loop()
    assert ctrl.shared.snapshot()["config_notice"] == ""


def test_sem_alvo_nao_ha_aviso_de_resolucao_mesmo_em_janela_pequena(ctrl, loop):
    loop(window_size=(1280, 720))
    assert ctrl.shared.snapshot()["config_notice"] == ""
