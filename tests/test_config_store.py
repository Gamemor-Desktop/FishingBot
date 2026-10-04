"""Testes do config_store, isolados num LOCALAPPDATA temporario."""
from __future__ import annotations

import json

import pytest

from fishingbot import config_store


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / config_store.APP_NAME


def test_primeira_carga_cria_arquivo_com_defaults(cfg_dir):
    cfg = config_store.load_config()
    assert cfg["keybinds"]["use_item_key"] == "4"
    assert (cfg_dir / "config.json").exists()


def test_override_do_usuario_e_preservado_e_chaves_novas_aparecem(cfg_dir):
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"timings": {"bite_timeout_seconds": 5}}))
    cfg = config_store.load_config()
    assert cfg["timings"]["bite_timeout_seconds"] == 5
    assert "pull_panel_first_appear_timeout_seconds" in cfg["timings"]


def test_config_corrompido_volta_aos_defaults_sem_travar(cfg_dir):
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{ isso nao e json")
    cfg = config_store.load_config()
    assert cfg["timings"] == config_store.DEFAULTS["timings"]


@pytest.mark.xfail(strict=True, reason=(
    "L3: a primeira execucao grava TODOS os defaults no config.json; depois "
    "disso, mudar DEFAULTS nunca chega ao usuario"))
def test_novo_default_chega_a_quem_nunca_editou_o_valor(cfg_dir, monkeypatch):
    config_store.load_config()  # grava o arquivo com os defaults de hoje
    novos = json.loads(json.dumps(config_store.DEFAULTS))
    novos["timings"]["end_confirm_seconds"] = 2.5
    monkeypatch.setattr(config_store, "DEFAULTS", novos)
    assert config_store.load_config()["timings"]["end_confirm_seconds"] == 2.5
