"""
Persistencia local de configuracao/calibracao. Fica em
%LOCALAPPDATA%\\FishingBot\\config.json -- fora da pasta do programa (que
pode estar num lugar read-only, tipo Arquivos de Programas, ou ser apagada e
reinstalada), como qualquer app Windows bem comportado.

Guarda: ultima resolucao/DPI/retangulo de janela detectados (so
informativo, pra mostrar na interface e decidir se precisa recalibrar), e
overrides opcionais de fracoes/cores/teclas que o usuario avancado queira
ajustar manualmente editando o json (nao ha interface pra isso ainda -- ver
README, secao "Configuracoes").
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

APP_NAME = "FishingBot"


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


DEFAULTS = {
    "last_window": {"width": None, "height": None, "left": None, "top": None},
    "last_dpi_scale": None,
    "last_calibrated_at": None,
    "keybinds": {
        "use_item_key": "4",
        "space_key": "space",
        "pull_key": "s",
        "release_key": "w",
    },
    "timings": {
        "bite_timeout_seconds": 90,
        "hit_timeout_seconds": 8,
        "pulling_timeout_seconds": 150,
        # quantos SEGUNDOS SEGUIDOS o painel "Calmo/Puxando forte" precisa
        # ficar ausente (sem bater com nenhuma cor configurada) antes do
        # bot considerar que a puxada terminou (peixe capturado/perdido).
        # E tempo real, nao contagem de frames -- de proposito: contar
        # frames (ex: "15 leituras seguidas sem match") depende de quao
        # rapido cada iteracao do loop roda nessa maquina, e podia passar
        # rapido demais (bem menos de 1s) e declarar "painel sumiu" por
        # causa de uma unica leitura ruim isolada (flicker de renderizacao),
        # gerando um falso "peixe capturado" quase junto com o ESPACO, antes
        # da puxada de verdade sequer comecar. Se isso ainda acontecer,
        # aumente este valor (ex: 1.5 ou 2.0).
        "end_confirm_seconds": 1.2,
        # quanto tempo esperar o painel "Calmo/Puxando forte" aparecer pela
        # PRIMEIRA vez depois do ESPACO, antes de desistir. Separado do
        # end_confirm_seconds (que serve pra detectar o painel SUMINDO
        # depois de ja ter aparecido) -- sem essa distincao, uma demora
        # normal de renderizacao do jogo (rede/frame) era tratada como
        # "peixe fugiu" antes mesmo do painel ter chance de aparecer.
        "pull_panel_first_appear_timeout_seconds": 3.0,
    },
    "fractions_override": {},
    "ui": {"start_minimized": False},
}


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
        save_config(cfg)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # config corrompido -- comeca do zero em vez de travar o programa
        data = {}

    # merge raso com os defaults, garantindo que chaves novas apareçam em
    # configs antigos sem apagar o que o usuario customizou
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def save_config(cfg: dict) -> None:
    path = config_path()
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)  # escrita atomica, evita corromper se cair no meio


def update_last_calibration(cfg: dict, width: int, height: int, left: int, top: int, dpi_scale: int) -> dict:
    cfg["last_window"] = {"width": width, "height": height, "left": left, "top": top}
    cfg["last_dpi_scale"] = dpi_scale
    cfg["last_calibrated_at"] = time.time()
    save_config(cfg)
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
