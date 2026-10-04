"""config_store: so overrides no arquivo, migracao, validacao e backup."""
from __future__ import annotations

import json

import pytest

from fishingbot import config_store as cs

# Copia (literal) do config.json real de um usuario, gravado pela versao antiga:
# TODOS os padroes foram gravados, e so pulling_timeout_seconds foi editado a mao.
LEGACY_REAL = {
    "last_window": {"width": 1920, "height": 1080, "left": 0, "top": 0},
    "last_dpi_scale": 100,
    "last_calibrated_at": 1791077014.277437,
    "keybinds": {"use_item_key": "4", "space_key": "space", "pull_key": "s",
                 "release_key": "w", "panic_key": "f10"},
    "timings": {"bite_timeout_seconds": 90, "hit_timeout_seconds": 8,
                "pulling_timeout_seconds": 600, "end_confirm_seconds": 1.2,
                "pull_panel_first_appear_timeout_seconds": 3.0,   # padrao ANTIGO (hoje 6.0)
                "after_confirm_delay_seconds": 1.5},
    "safety": {"max_consecutive_failures": 5, "progress_timeout_minutes": 15,
               "retry_backoff_base_seconds": 0.5, "retry_backoff_max_seconds": 5.0,
               "black_screen_seconds": 3.0, "frozen_screen_seconds": 15.0},
    "fractions_override": {},
    "ui": {"start_minimized": False},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / cs.APP_NAME
    d.mkdir()
    return d


def _write(env, data):
    (env / "config.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _on_disk(env) -> dict:
    return json.loads((env / "config.json").read_text(encoding="utf-8"))


# -- primeira execucao e "so overrides" ---------------------------------------------------

def test_primeira_carga_grava_so_a_versao_e_uma_referencia_dos_padroes(env):
    cfg, warnings = cs.load_config_with_report()
    assert warnings == []
    assert cfg["keybinds"]["use_item_key"] == "4"
    assert _on_disk(env) == {"config_version": cs.CONFIG_VERSION}
    ref = json.loads((env / "config.reference.json").read_text(encoding="utf-8"))
    assert ref["timings"]["pull_min_seconds"] == cs.DEFAULTS["timings"]["pull_min_seconds"]


def test_arquivo_guarda_so_o_que_difere_dos_padroes_mais_o_estado(env):
    cfg = cs.load_config()
    cfg["timings"]["hit_timeout_seconds"] = 12
    cs.update_last_calibration(cfg, 1280, 720, 10, 20, 125)
    disk = _on_disk(env)
    assert disk["timings"] == {"hit_timeout_seconds": 12}
    assert disk["last_window"] == {"width": 1280, "height": 720, "left": 10, "top": 20}
    assert disk["last_dpi_scale"] == 125
    assert "keybinds" not in disk and "safety" not in disk and "ui" not in disk


def test_novo_default_chega_a_quem_nunca_editou_o_valor(env, monkeypatch):
    """O bug L3: antes, o 1o save congelava todos os padroes no arquivo."""
    cfg = cs.load_config()
    cs.update_last_calibration(cfg, 1920, 1080, 0, 0, 100)   # causa uma gravacao completa
    novos = json.loads(json.dumps(cs.DEFAULTS))
    novos["timings"]["end_confirm_seconds"] = 2.5
    monkeypatch.setattr(cs, "DEFAULTS", novos)
    assert cs.load_config()["timings"]["end_confirm_seconds"] == 2.5


def test_override_do_usuario_e_preservado_e_chaves_novas_aparecem(env):
    _write(env, {"config_version": 2, "timings": {"bite_timeout_seconds": 30}})
    cfg = cs.load_config()
    assert cfg["timings"]["bite_timeout_seconds"] == 30
    assert cfg["timings"]["pull_min_seconds"] == cs.DEFAULTS["timings"]["pull_min_seconds"]
    assert cfg["safety"]["max_consecutive_failures"] == 5


# -- migracao do config antigo -----------------------------------------------------------------

def test_migracao_mantem_so_a_personalizacao_e_descarta_padroes_gravados(env):
    _write(env, LEGACY_REAL)
    cfg, warnings = cs.load_config_with_report()
    assert warnings == []
    disk = _on_disk(env)
    assert disk["config_version"] == cs.CONFIG_VERSION
    assert disk["timings"] == {"pulling_timeout_seconds": 600}, "so o que o usuario editou"
    assert "safety" not in disk and "keybinds" not in disk
    assert disk["last_window"]["width"] == 1920, "o estado da calibracao e preservado"
    # em memoria: personalizacao mantida, padrao novo aplicado onde era valor antigo
    assert cfg["timings"]["pulling_timeout_seconds"] == 600
    assert cfg["timings"]["pull_panel_first_appear_timeout_seconds"] == 6.0
    assert cfg["timings"]["pull_min_seconds"] == 8.0


def test_migracao_guarda_o_original(env):
    _write(env, LEGACY_REAL)
    cs.load_config()
    assert json.loads((env / "config.json.v1.bak").read_text(encoding="utf-8")) == LEGACY_REAL


def test_migracao_nao_descarta_valor_personalizado_igual_a_nada_conhecido(env):
    legacy = json.loads(json.dumps(LEGACY_REAL))
    legacy["keybinds"]["pull_key"] = "j"
    legacy["safety"]["max_consecutive_failures"] = 9
    _write(env, legacy)
    cfg = cs.load_config()
    assert cfg["keybinds"]["pull_key"] == "j" and cfg["safety"]["max_consecutive_failures"] == 9
    assert _on_disk(env)["keybinds"] == {"pull_key": "j"}


def test_depois_de_migrar_nao_migra_de_novo(env):
    _write(env, LEGACY_REAL)
    cs.load_config()
    before = _on_disk(env)
    (env / "config.json.v1.bak").unlink()
    cs.load_config()
    assert _on_disk(env) == before
    assert not (env / "config.json.v1.bak").exists()


# -- arquivo corrompido -----------------------------------------------------------------------------

@pytest.mark.parametrize("conteudo", ["{ isso nao e json", "", "[1, 2, 3]", '"texto"', "null"])
def test_config_ilegivel_vira_padroes_e_o_original_fica_em_bak(env, conteudo):
    _write(env, conteudo)
    cfg, warnings = cs.load_config_with_report()
    assert cfg["timings"] == cs.DEFAULTS["timings"]
    assert any("ilegivel" in w for w in warnings)
    assert (env / "config.json.bak").read_text(encoding="utf-8") == conteudo
    assert _on_disk(env) == {"config_version": cs.CONFIG_VERSION}


def test_config_de_versao_mais_nova_avisa_mas_carrega(env):
    _write(env, {"config_version": 99, "timings": {"bite_timeout_seconds": 20}})
    cfg, warnings = cs.load_config_with_report()
    assert cfg["timings"]["bite_timeout_seconds"] == 20
    assert any("mais nova" in w for w in warnings)


# -- validacao -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("secao,chave,ruim", [
    ("timings", "hit_timeout_seconds", -3),
    ("timings", "hit_timeout_seconds", 0),
    ("timings", "bite_timeout_seconds", "noventa"),
    ("timings", "end_confirm_seconds", True),            # bool nao e numero
    ("timings", "pull_min_seconds", None),
    ("timings", "pulling_timeout_seconds", 10 ** 9),
    ("timings", "after_confirm_delay_seconds", float("nan")),
    ("safety", "max_consecutive_failures", 0),           # 0 desligaria o disjuntor
    ("safety", "max_consecutive_failures", 2.5),         # tem que ser inteiro
    ("safety", "retry_backoff_base_seconds", -1),
    ("keybinds", "pull_key", ""),
    ("keybinds", "pull_key", 5),
    ("keybinds", "panic_key", "x" * 50),
    ("ui", "start_minimized", "sim"),
])
def test_valor_invalido_volta_ao_padrao_com_aviso(env, secao, chave, ruim):
    _write(env, {"config_version": 2, secao: {chave: ruim}})
    raw = (env / "config.json").read_text(encoding="utf-8")   # NaN nao e JSON estrito, mas json aceita
    cfg, warnings = cs.load_config_with_report()
    assert cfg[secao][chave] == cs.DEFAULTS[secao][chave], raw
    assert any(f"{secao}.{chave}" in w for w in warnings)


def test_um_valor_ruim_nao_atrapalha_os_outros(env):
    _write(env, {"config_version": 2, "timings": {"hit_timeout_seconds": -1, "bite_timeout_seconds": 20}})
    cfg = cs.load_config()
    assert cfg["timings"]["bite_timeout_seconds"] == 20
    assert cfg["timings"]["hit_timeout_seconds"] == cs.DEFAULTS["timings"]["hit_timeout_seconds"]


def test_secao_com_tipo_errado_volta_ao_padrao(env):
    _write(env, {"config_version": 2, "timings": "rapido", "safety": [1]})
    cfg, warnings = cs.load_config_with_report()
    assert cfg["timings"] == cs.DEFAULTS["timings"] and cfg["safety"] == cs.DEFAULTS["safety"]
    assert len(warnings) >= 2


def test_chave_desconhecida_avisa_mas_nao_quebra(env):
    _write(env, {"config_version": 2, "timings": {"bite_timeout": 20}, "outra_coisa": 1})
    cfg, warnings = cs.load_config_with_report()
    assert cfg["timings"]["bite_timeout_seconds"] == cs.DEFAULTS["timings"]["bite_timeout_seconds"]
    assert any("bite_timeout" in w and "desconhecida" in w for w in warnings)
    assert any("outra_coisa" in w for w in warnings)


def test_fractions_override_valido_passa_e_invalido_e_ignorado(env):
    _write(env, {"config_version": 2, "fractions_override": {
        "hook_zone": {"fx": 0.40, "fy": 0.5},
        "regiao_que_nao_existe": {"fx": 0.1},
        "pulling_state": {"fx": 5.0},               # fora de 0..1
    }})
    cfg, warnings = cs.load_config_with_report()
    assert cfg["fractions_override"] == {"hook_zone": {"fx": 0.40, "fy": 0.5}}
    assert len(warnings) == 2


def test_fractions_override_com_chave_invalida_e_ignorado(env):
    _write(env, {"config_version": 2, "fractions_override": {"pulling_state": {"zz": 0.1}}})
    cfg, warnings = cs.load_config_with_report()
    assert cfg["fractions_override"] == {}
    assert len(warnings) == 1


def test_estado_da_calibracao_com_tipo_errado_nao_quebra_a_comparacao(env):
    _write(env, {"config_version": 2, "last_window": "oops", "last_dpi_scale": "alto",
                 "last_calibrated_at": "ontem"})
    cfg = cs.load_config()
    assert cs.needs_recalibration(cfg, 1920, 1080, 0, 0, 100) is True


# -- value() e gravacao -----------------------------------------------------------------------------------

def test_value_cai_no_padrao_se_o_valor_em_memoria_for_ruim():
    cfg = cs.load_config.__globals__["copy"].deepcopy(cs.DEFAULTS)
    cfg["safety"]["max_consecutive_failures"] = "cinco"
    cfg["timings"].pop("pull_min_seconds")
    assert cs.value(cfg, "safety", "max_consecutive_failures") == 5
    assert cs.value(cfg, "timings", "pull_min_seconds") == cs.DEFAULTS["timings"]["pull_min_seconds"]
    assert cs.value({}, "timings", "bite_timeout_seconds") == 90
    assert cs.value(None, "timings", "bite_timeout_seconds") == 90


def test_falha_ao_gravar_a_calibracao_nao_derruba_o_bot(env, monkeypatch):
    cfg = cs.load_config()

    def boom(_cfg):
        raise PermissionError("arquivo em uso")
    monkeypatch.setattr(cs, "save_config", boom)
    out = cs.update_last_calibration(cfg, 1920, 1080, 0, 0, 100)   # nao levanta
    assert out["last_window"]["width"] == 1920


def test_falha_ao_gravar_na_carga_vira_aviso(env, monkeypatch):
    monkeypatch.setattr(cs, "save_config", lambda _c: (_ for _ in ()).throw(OSError("somente leitura")))
    cfg, warnings = cs.load_config_with_report()
    assert cfg["timings"] == cs.DEFAULTS["timings"]
    assert any("nao consegui gravar" in w for w in warnings)


def test_gravacao_nao_deixa_arquivo_temporario(env):
    cfg = cs.load_config()
    cs.update_last_calibration(cfg, 1920, 1080, 0, 0, 100)
    assert not list(env.glob("*.tmp"))
