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
MAX_AGE_DAYS = 7
MAX_DEBUG_MB = 100          # teto de tamanho da pasta debug/ (apaga os mais antigos)
PRUNE_EVERY_SAVES = 200     # a cada quantos PNGs salvos reconferir o teto
_saves_since_prune = 0


def prune_files(max_age_days: float = MAX_AGE_DAYS, max_bytes: int = MAX_DEBUG_MB * 1024 * 1024) -> int:
    """Apaga PNGs de debug com mais de `max_age_days` e, depois, os mais antigos
    ate a pasta caber em `max_bytes`. Os nomes de arquivo so tem HHMMSS (sem
    data), entao sem isso a pasta cresce pra sempre: uma sessao longa com
    --debug passa de 100 MB. Devolve quantos arquivos removeu."""
    cutoff = time.time() - max_age_days * 86400
    files = []
    for png in debug_dir().glob("*.png"):
        try:
            st = png.stat()
            files.append((st.st_mtime, st.st_size, png))
        except OSError:
            pass
    removed = 0
    kept = []
    for mtime, size, png in files:
        if mtime < cutoff:
            try:
                png.unlink()
                removed += 1
                continue
            except OSError:
                pass
        kept.append((mtime, size, png))
    kept.sort(key=lambda f: f[0])
    total = sum(f[1] for f in kept)
    while total > max_bytes and kept:
        _mtime, size, png = kept.pop(0)
        try:
            png.unlink()
            removed += 1
            total -= size
        except OSError:
            pass
    return removed


def enable() -> None:
    global _enabled
    _enabled = True
    debug_dir().mkdir(parents=True, exist_ok=True)
    removed = prune_files()
    if removed:
        log.info(f"[debug] {removed} screenshot(s) antigos removidos de {debug_dir()} "
                 f"(limite: {MAX_AGE_DAYS} dias / {MAX_DEBUG_MB} MB)")
    log.info(f"Modo debug ativado -- screenshots e proporcoes de cor em {debug_dir()}")


def is_enabled() -> bool:
    return _enabled


def debug_dir() -> Path:
    return config_store.config_dir() / "debug"


def log_ratio(name: str, ratio: float, threshold: float | None, extra: str = "") -> None:
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
    if threshold is None:  # sinal sem limiar proprio (ex: bolinha, decidida por forma)
        log.debug(f"[debug] {name}: ratio={ratio:.4f} {extra}")
        return
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
        return
    global _saves_since_prune
    _saves_since_prune += 1
    if _saves_since_prune >= PRUNE_EVERY_SAVES:
        _saves_since_prune = 0
        prune_files()
