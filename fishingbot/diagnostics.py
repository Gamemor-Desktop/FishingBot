"""
Pacote de diagnostico: quando o bot se desliga sozinho (disjuntor de falhas
seguidas, travamento de progresso), salva em
%LOCALAPPDATA%\\FishingBot\\diagnostics\\<data_hora>\\ tudo que e preciso pra
entender o que ele estava vendo, sem depender de lembrar de ter ligado o
--debug:

  motivo.txt        por que parou + estatisticas + teclas/timings em uso
  log_recente.txt   as ultimas linhas do log (memoria, sem depender do arquivo)
  janela.png        a janela do jogo inteira naquele instante
  regiao_<nome>.png cada regiao de reconhecimento naquele instante

Tudo fica so no seu PC. Mantem os ultimos MAX_BUNDLES pacotes.
"""
from __future__ import annotations

import collections
import json
import logging
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from . import config_store

log = logging.getLogger("fishingbot")

MAX_BUNDLES = 10


class RingLogHandler(logging.Handler):
    """Guarda as ultimas `maxlen` linhas de log em memoria."""

    def __init__(self, maxlen: int = 300):
        super().__init__(level=logging.DEBUG)
        self.lines: collections.deque[str] = collections.deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            pass


ring = RingLogHandler()


def install_ring_handler() -> None:
    root = logging.getLogger()
    if ring not in root.handlers:
        root.addHandler(ring)


def diagnostics_dir() -> Path:
    return config_store.config_dir() / "diagnostics"


def _prune(base: Path) -> None:
    bundles = sorted(p for p in base.iterdir() if p.is_dir())
    for old in bundles[:-MAX_BUNDLES]:
        shutil.rmtree(old, ignore_errors=True)


def save_bundle(reason: str, sct, window, regions: dict, stats_text: str,
                cfg: dict) -> Path | None:
    """Grava o pacote e devolve a pasta (None se nao conseguiu). Nunca levanta
    excecao: estamos justamente no meio de uma falha."""
    try:
        base = diagnostics_dir()
        base.mkdir(parents=True, exist_ok=True)
        folder = base / time.strftime("%Y%m%d_%H%M%S")
        folder.mkdir(exist_ok=True)

        (folder / "motivo.txt").write_text(
            f"{reason}\n\n{stats_text}\n\n"
            f"janela: {window.width}x{window.height} em ({window.left},{window.top})\n\n"
            + json.dumps({"keybinds": cfg.get("keybinds"), "timings": cfg.get("timings"),
                          "safety": cfg.get("safety")}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        (folder / "log_recente.txt").write_text("\n".join(ring.lines), encoding="utf-8")

        def _save(name: str, rect: dict) -> None:
            try:
                img = cv2.cvtColor(np.array(sct.grab(rect)), cv2.COLOR_BGRA2BGR)
                cv2.imwrite(str(folder / name), img)
            except Exception:
                log.exception(f"Diagnostico: falha ao salvar {name}")

        _save("janela.png", {"left": window.left, "top": window.top,
                             "width": window.width, "height": window.height})
        for rname, r in regions.items():
            _save(f"regiao_{rname}.png", {"left": r.x, "top": r.y, "width": r.w, "height": r.h})

        _prune(base)
        log.info(f"Pacote de diagnostico salvo em {folder}")
        return folder
    except Exception:
        log.exception("Falha ao salvar o pacote de diagnostico")
        return None
