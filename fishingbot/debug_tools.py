"""
Ferramentas de diagnostico visual, ativadas com `--debug`. Servem pra
responder uma pergunta especifica sem precisar adivinhar: a fase de puxar
(ou a de fisgar) nao esta funcionando porque a REGIAO capturada nao esta
alinhada com o painel do jogo, ou porque a COR configurada nao bate com o
que aparece na tela deste usuario (skin de UI diferente, servidor com HUD
customizado, etc)?

Com --debug ativo:
  - a cada frame processado, loga (nivel DEBUG) a proporcao de pixels que
    bateu com cada faixa de cor, junto do limite configurado -- da pra ver
    se o valor esta sempre em 0 (regiao errada / cor muito diferente) ou
    perto do limite mas nao o suficiente (so ajustar o threshold resolve).
  - salva um PNG da regiao capturada (e da mascara aplicada) em
    %LOCALAPPDATA%\\FishingBot\\debug\\, no maximo 1x por segundo por nome,
    pra abrir e comparar lado a lado com o jogo.

As capturas sao throttled (1x/segundo por nome) de proposito -- o loop de
automacao roda a cada 20-50ms, salvar toda iteracao encheria o disco rapido
sem ganhar nada (a imagem nao muda tanto assim entre frames tao proximos).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from . import config_store

log = logging.getLogger("fishingbot")

_enabled = False
_last_event: dict[str, float] = {}

SAVE_INTERVAL_SECONDS = 1.0
LOG_INTERVAL_SECONDS = 0.25


def enable() -> None:
    global _enabled
    _enabled = True
    debug_dir().mkdir(parents=True, exist_ok=True)
    log.info(f"Modo debug ativado -- screenshots e proporcoes de cor em {debug_dir()}")


def is_enabled() -> bool:
    return _enabled


def debug_dir() -> Path:
    return config_store.config_dir() / "debug"


def log_ratio(name: str, ratio: float, threshold: float, extra: str = "") -> None:
    """Loga (nivel DEBUG, throttled) a proporcao de pixels calculada pra
    `name` nesta iteracao, junto do limite configurado pra bater a
    deteccao. Chamado toda iteracao do loop de automacao, mas so imprime de
    fato no maximo 4x/segundo por nome."""
    if not _enabled:
        return
    now = time.time()
    key = f"log_{name}"
    if now - _last_event.get(key, 0.0) < LOG_INTERVAL_SECONDS:
        return
    _last_event[key] = now
    marca = "OK" if ratio >= threshold else "abaixo do limite"
    log.debug(f"[debug] {name}: ratio={ratio:.4f} limite={threshold:.4f} ({marca}) {extra}")


def save_roi(name: str, frame_bgr: np.ndarray, mask: np.ndarray | None = None) -> None:
    """Salva a regiao capturada (e a mascara HSV, se fornecida) como PNG.
    Throttled a 1x/segundo por `name` pra nao encher o disco. Abra os PNGs
    gerados e compare com o que aparece no jogo naquele instante: se o
    recorte nao mostra o painel certo, a regiao (fractions_override) precisa
    de ajuste; se o recorte mostra o painel certo mas a mascara fica toda
    preta, a cor (DEFAULT_COLORS) e que precisa de ajuste."""
    if not _enabled:
        return
    now = time.time()
    if now - _last_event.get(name, 0.0) < SAVE_INTERVAL_SECONDS:
        return
    _last_event[name] = now
    try:
        import cv2
        ts = time.strftime("%H%M%S")
        cv2.imwrite(str(debug_dir() / f"{name}_{ts}.png"), frame_bgr)
        if mask is not None:
            cv2.imwrite(str(debug_dir() / f"{name}_{ts}_mask.png"), mask)
    except Exception:
        log.exception(f"Falha ao salvar screenshot de debug ({name})")
