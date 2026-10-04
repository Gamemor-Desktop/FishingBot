"""
Persistencia local de configuracao/calibracao, em
%LOCALAPPDATA%\\FishingBot\\config.json -- fora da pasta do programa (que pode
estar num lugar read-only ou ser apagada e reinstalada).

Regras (o porque de cada uma esta em docs/calibracao.md):

- O arquivo guarda SO o que difere dos padroes (`DEFAULTS`) + o estado da
  ultima calibracao. Antes ele gravava TODOS os padroes na primeira execucao,
  e dai em diante mudar um padrao nunca chegava ao usuario: o valor antigo
  ficava "congelado" no arquivo como se fosse escolha dele. A lista completa
  e atual de padroes fica em `config.reference.json` (regravado a cada abertura,
  so pra consulta -- editar esse arquivo nao tem efeito).
- Configs antigos (sem `config_version`) sao migrados: valor igual ao padrao
  atual ou a algum padrao historico (`LEGACY_DEFAULTS`) nao e personalizacao e
  e descartado; o resto e mantido. O arquivo original vira `config.json.v1.bak`.
- Todo valor e validado (tipo e faixa, `SCHEMA`); valor invalido volta ao padrao
  com um aviso -- config editado a mao nunca deve derrubar o bot nem criar um
  loop sem espera. Arquivo ilegivel e copiado pra `config.json.bak` antes de
  ser descartado.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import shutil
import sys
import time
from pathlib import Path

log = logging.getLogger("fishingbot")

APP_NAME = "FishingBot"
CONFIG_VERSION = 2


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


# ---------------------------------------------------------------------------
# Padroes (fonte UNICA: nenhum outro lugar repete esses numeros)
# ---------------------------------------------------------------------------

DEFAULTS = {
    # estado da ultima calibracao (informativo; ver needs_recalibration)
    "last_window": {"width": None, "height": None, "left": None, "top": None},
    "last_dpi_scale": None,
    "last_calibrated_at": None,
    "keybinds": {
        "use_item_key": "4",
        "space_key": "space",
        "pull_key": "s",
        "release_key": "w",
        "panic_key": "f10",   # parada de emergencia global (panic.py)
    },
    "timings": {
        "bite_timeout_seconds": 90,
        "hit_timeout_seconds": 8,
        "pulling_timeout_seconds": 150,
        "end_confirm_seconds": 1.2,                        # painel ausente por tanto = puxada acabou
        "pull_panel_first_appear_timeout_seconds": 6.0,    # espera o painel aparecer apos o ESPACO
        "after_confirm_delay_seconds": 1.5,                # folga depois do ENTER
        "pull_min_seconds": 8.0,                           # puxada nao termina antes disso
        "cast_confirm_seconds": 45.0,                      # sem mordida: avisa pra conferir a pesca
    },
    "safety": {
        "max_consecutive_failures": 5,
        "progress_timeout_minutes": 15,
        "retry_backoff_base_seconds": 0.5,
        "retry_backoff_max_seconds": 5.0,
        "black_screen_seconds": 3.0,
        "frozen_screen_seconds": 15.0,
        "pause_timeout_seconds": 120,
    },
    "fractions_override": {},
    "ui": {"start_minimized": False},
}

# Valores que ja foram padrao em versoes anteriores. Num config antigo, um valor
# igual a eles (alem do padrao atual) so estava ali porque o programa o gravou,
# nao porque o usuario escolheu -- entao nao conta como personalizacao.
LEGACY_DEFAULTS: dict[tuple[str, str], set] = {
    ("timings", "pull_panel_first_appear_timeout_seconds"): {3.0},
    ("timings", "cast_confirm_seconds"): {12.0},
}

# (tipo, minimo, maximo). Tipos: "num" (int/float finito), "int", "bool", "key".
SCHEMA: dict[tuple[str, str], tuple] = {
    ("timings", "bite_timeout_seconds"): ("num", 5, 600),
    ("timings", "hit_timeout_seconds"): ("num", 1, 60),
    ("timings", "pulling_timeout_seconds"): ("num", 10, 1800),
    ("timings", "end_confirm_seconds"): ("num", 0.3, 10),
    ("timings", "pull_panel_first_appear_timeout_seconds"): ("num", 1, 30),
    ("timings", "after_confirm_delay_seconds"): ("num", 0, 30),
    ("timings", "pull_min_seconds"): ("num", 0, 60),
    ("timings", "cast_confirm_seconds"): ("num", 5, 600),
    ("safety", "max_consecutive_failures"): ("int", 1, 100),
    ("safety", "progress_timeout_minutes"): ("num", 1, 240),
    ("safety", "retry_backoff_base_seconds"): ("num", 0, 30),
    ("safety", "retry_backoff_max_seconds"): ("num", 0, 120),
    ("safety", "black_screen_seconds"): ("num", 0.5, 60),
    ("safety", "frozen_screen_seconds"): ("num", 1, 600),
    ("safety", "pause_timeout_seconds"): ("num", 5, 3600),
    ("keybinds", "use_item_key"): ("key",),
    ("keybinds", "space_key"): ("key",),
    ("keybinds", "pull_key"): ("key",),
    ("keybinds", "release_key"): ("key",),
    ("keybinds", "panic_key"): ("key",),
    ("ui", "start_minimized"): ("bool",),
}

_STATE_KEYS = ("last_window", "last_dpi_scale", "last_calibrated_at")
_FRACTION_KEYS = ("fx", "fy", "fw", "fh")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _valid(rule: tuple, v) -> bool:
    kind = rule[0]
    if kind == "bool":
        return isinstance(v, bool)
    if kind == "key":
        return isinstance(v, str) and 0 < len(v.strip()) <= 20
    if kind == "int":
        return isinstance(v, int) and not isinstance(v, bool) and rule[1] <= v <= rule[2]
    return _is_number(v) and rule[1] <= v <= rule[2]


def _describe(rule: tuple) -> str:
    if rule[0] == "bool":
        return "true/false"
    if rule[0] == "key":
        return "nome de tecla (texto)"
    return f"{'inteiro' if rule[0] == 'int' else 'numero'} entre {rule[1]} e {rule[2]}"


def value(cfg: dict, section: str, key: str):
    """Valor validado de cfg[section][key]; se estiver ausente ou invalido
    (mesmo que alguem tenha mexido no dict em memoria), devolve o padrao."""
    default = DEFAULTS[section][key]
    sec = cfg.get(section) if isinstance(cfg, dict) else None
    v = sec.get(key, default) if isinstance(sec, dict) else default
    rule = SCHEMA.get((section, key))
    return v if rule is None or _valid(rule, v) else default


# ---------------------------------------------------------------------------
# merge / diff / validacao
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, over: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _diff(cfg: dict, base: dict) -> dict:
    """So o que difere de `base` (recursivo)."""
    out = {}
    for k, v in cfg.items():
        if k not in base:
            out[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(base[k], dict):
            d = _diff(v, base[k])
            if d:
                out[k] = d
        elif v != base[k]:
            out[k] = copy.deepcopy(v)
    return out


def validate(cfg: dict) -> tuple[dict, list[str]]:
    """Devolve (config corrigido, avisos). Valores invalidos voltam ao padrao."""
    from .regions import DEFAULT_FRACTIONS  # import tardio: evita ciclo

    out = copy.deepcopy(cfg)
    warnings: list[str] = []

    for section, defaults in DEFAULTS.items():
        if isinstance(defaults, dict) and not isinstance(out.get(section), dict):
            warnings.append(f"'{section}' devia ser um bloco {{...}}; usando os padroes")
            out[section] = copy.deepcopy(defaults)

    for (section, key), rule in SCHEMA.items():
        v = out[section].get(key)
        if not _valid(rule, v):
            default = DEFAULTS[section][key]
            warnings.append(f"{section}.{key}={v!r} invalido (esperado {_describe(rule)}); usando {default!r}")
            out[section][key] = default

    # estado da calibracao: so informativo, mas tipos errados quebrariam a comparacao
    if not isinstance(out["last_window"], dict):
        out["last_window"] = copy.deepcopy(DEFAULTS["last_window"])
    for k in ("width", "height", "left", "top"):
        v = out["last_window"].get(k)
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool)):
            out["last_window"][k] = None
    if out["last_dpi_scale"] is not None and not _is_number(out["last_dpi_scale"]):
        out["last_dpi_scale"] = None
    if out["last_calibrated_at"] is not None and not _is_number(out["last_calibrated_at"]):
        out["last_calibrated_at"] = None

    # ajuste fino das regioes
    fractions = out["fractions_override"]
    for region in list(fractions):
        entry = fractions[region]
        ok = (region in DEFAULT_FRACTIONS and isinstance(entry, dict) and entry
              and all(k in _FRACTION_KEYS and _is_number(v) and 0 <= v <= 1 for k, v in entry.items()))
        if not ok:
            warnings.append(f"fractions_override.{region} invalido (regiao desconhecida ou "
                            f"valores fora de 0..1); ignorado")
            del fractions[region]

    # chaves desconhecidas: provavelmente erro de digitacao (continuam no arquivo)
    for section, defaults in DEFAULTS.items():
        if section in _STATE_KEYS or section == "fractions_override":
            continue
        if isinstance(defaults, dict):
            for k in out[section]:
                if k not in defaults:
                    warnings.append(f"{section}.{k}: chave desconhecida (erro de digitacao?); ignorada")
    for k in out:
        if k not in DEFAULTS:
            warnings.append(f"'{k}': secao desconhecida; ignorada")
    return out, warnings


def _migrate_legacy(data: dict) -> dict:
    """Config sem config_version: descarta o que so era o padrao gravado pelo
    programa (igual ao padrao atual ou a um historico); mantem o resto."""
    out = copy.deepcopy(data)
    for section, defaults in DEFAULTS.items():
        sec = out.get(section)
        if not isinstance(defaults, dict) or section in _STATE_KEYS or section == "fractions_override":
            continue
        if not isinstance(sec, dict):
            continue
        for key, default in defaults.items():
            if key in sec and (sec[key] == default or sec[key] in LEGACY_DEFAULTS.get((section, key), ())):
                del sec[key]
        if not sec:
            del out[section]
    return out


# ---------------------------------------------------------------------------
# leitura / gravacao
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    last: OSError | None = None
    for _ in range(3):  # antivirus/indexador as vezes seguram o arquivo por instantes
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp.replace(path)  # escrita atomica: nunca deixa um arquivo pela metade
            return
        except OSError as exc:
            last = exc
            time.sleep(0.1)
    assert last is not None
    raise last


def save_config(cfg: dict) -> None:
    """Grava so o que difere dos padroes (+ versao). Levanta OSError se nao der."""
    _atomic_write(config_path(), {"config_version": CONFIG_VERSION, **_diff(cfg, DEFAULTS)})


def _write_reference() -> None:
    try:
        _atomic_write(config_dir() / "config.reference.json", {
            "_aviso": "Padroes atuais, so pra consulta. Editar ESTE arquivo nao tem efeito: "
                      "coloque no config.json apenas os valores que quer mudar.",
            **DEFAULTS,
        })
    except OSError:
        pass


def load_config_with_report() -> tuple[dict, list[str]]:
    """Carrega, migra e valida. Devolve (config, avisos pra mostrar/logar)."""
    path = config_path()
    warnings: list[str] = []
    data: dict = {}
    must_save = not path.exists()

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("o conteudo nao e um objeto JSON")
            data = loaded
        except Exception as exc:
            backup = path.with_suffix(".json.bak")
            try:
                shutil.copy2(path, backup)
                where = f"copia em {backup.name}"
            except OSError:
                where = "nao foi possivel copiar"
            warnings.append(f"config.json ilegivel ({exc}); {where}; usando os padroes")
            data, must_save = {}, True
        else:
            version = data.pop("config_version", 1)
            if not isinstance(version, int) or isinstance(version, bool):
                version = 1
            if version < CONFIG_VERSION:
                try:
                    shutil.copy2(path, path.with_suffix(".json.v1.bak"))
                except OSError:
                    pass
                data = _migrate_legacy(data)
                must_save = True
                log.info("config.json antigo migrado: so as suas personalizacoes foram mantidas "
                         "(original em config.json.v1.bak)")
            elif version > CONFIG_VERSION:
                warnings.append(f"config.json foi criado por uma versao mais nova (v{version}); "
                                f"alguns campos podem ser ignorados")

    cfg, problems = validate(_deep_merge(DEFAULTS, data))
    warnings += problems

    if must_save:
        try:
            save_config(cfg)
        except OSError as exc:
            warnings.append(f"nao consegui gravar config.json ({exc})")
    _write_reference()
    return cfg, warnings


def load_config() -> dict:
    cfg, warnings = load_config_with_report()
    for w in warnings:
        log.warning(f"Config: {w}")
    return cfg


def update_last_calibration(cfg: dict, width: int, height: int, left: int, top: int, dpi_scale: int) -> dict:
    cfg["last_window"] = {"width": width, "height": height, "left": left, "top": top}
    cfg["last_dpi_scale"] = dpi_scale
    cfg["last_calibrated_at"] = time.time()
    try:
        save_config(cfg)
    except OSError as exc:
        # nao poder gravar o estado da calibracao nao pode derrubar o bot
        log.warning(f"Config: nao consegui gravar a calibracao ({exc}); segue sem salvar")
    return cfg


def needs_recalibration(cfg: dict, width: int, height: int, left: int, top: int, dpi_scale: int) -> bool:
    """A 'recalibracao' aqui e barata (so recalcular a formula fracao->pixel
    com o novo retangulo), entao na pratica isso roda toda vez que o
    retangulo muda -- mas mantemos a checagem pra decidir quando vale a pena
    tambem regravar o config.json (evita escrever disco a cada frame)."""
    last = cfg.get("last_window") or {}
    return (
        last.get("width") != width
        or last.get("height") != height
        or last.get("left") != left
        or last.get("top") != top
        or cfg.get("last_dpi_scale") != dpi_scale
    )
