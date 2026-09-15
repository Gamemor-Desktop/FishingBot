"""
Wrapper fino sobre pydirectinput para simular teclado de um jeito que jogos
baseados em DirectInput (GTA V / FiveM) reconhecem de forma confiavel.
Mantem controle de quais teclas estao "seguradas" para conseguir soltar tudo
de emergencia (panic key / Ctrl+C / crash).
"""
from __future__ import annotations

import threading
import time

import pydirectinput

pydirectinput.PAUSE = 0.0  # controlamos o timing manualmente no loop principal

_held_keys: set[str] = set()
_lock = threading.Lock()


def key_down(key: str) -> None:
    with _lock:
        if key not in _held_keys:
            pydirectinput.keyDown(key)
            _held_keys.add(key)


def key_up(key: str) -> None:
    with _lock:
        if key in _held_keys:
            pydirectinput.keyUp(key)
            _held_keys.discard(key)


def tap(key: str, hold_seconds: float = 0.03) -> None:
    pydirectinput.keyDown(key)
    time.sleep(hold_seconds)
    pydirectinput.keyUp(key)


def release_all() -> None:
    """Solta TODAS as teclas atualmente seguradas por este processo. Chame sempre
    no finally do loop principal e no handler de panic key."""
    with _lock:
        for key in list(_held_keys):
            try:
                pydirectinput.keyUp(key)
            except Exception:
                pass
        _held_keys.clear()


def ensure_only(key: str | None) -> None:
    """Garante que, dentre um grupo mutuamente exclusivo (ex: W vs D), apenas
    `key` (ou nenhuma, se None) esteja pressionada."""
    with _lock:
        for k in list(_held_keys):
            if k != key:
                try:
                    pydirectinput.keyUp(k)
                except Exception:
                    pass
                _held_keys.discard(k)
        if key is not None and key not in _held_keys:
            pydirectinput.keyDown(key)
            _held_keys.add(key)
