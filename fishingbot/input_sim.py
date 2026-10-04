"""
Wrapper fino sobre pydirectinput para simular teclado de um jeito que jogos
baseados em DirectInput (GTA V / FiveM) reconhecem de forma confiavel.
Mantem controle de quais teclas estao "seguradas" para conseguir soltar tudo
de emergencia (tecla de panico / fechar o app / crash).

Guarda de foco: SendInput sempre vai pra janela em primeiro plano do
sistema. Se o FiveM perdeu o foco (alt-tab, notificacao, outro app), mandar
tecla significa digitar S/W/4/ESPACO em OUTRO programa. Por isso o
controlador registra uma guarda (set_focus_guard) e toda funcao que ENVIA
tecla a consulta antes: se o foco nao esta no jogo, nada e enviado, tudo que
estava segurado e solto e FocusLostError sobe ate o controlador, que para o
bot. Soltar teclas nunca passa pela guarda (soltar e sempre seguro).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import pydirectinput

pydirectinput.PAUSE = 0.0  # controlamos o timing manualmente no loop principal

_held_keys: set[str] = set()
_lock = threading.Lock()
_focus_guard: Callable[[], bool] | None = None


class FocusLostError(RuntimeError):
    """O jogo nao esta em primeiro plano: nenhuma tecla foi enviada."""


def set_focus_guard(guard: Callable[[], bool] | None) -> None:
    """Registra (ou remove, com None) a funcao que diz se e seguro enviar
    teclas agora -- tipicamente `lambda: is_foreground(hwnd_do_jogo)`."""
    global _focus_guard
    _focus_guard = guard


def _require_focus() -> None:
    guard = _focus_guard
    if guard is None:
        return
    ok = False
    try:
        ok = bool(guard())
    except Exception:
        ok = False  # na duvida, nao envia
    if not ok:
        release_all()
        raise FocusLostError("O FiveM nao esta em primeiro plano -- tecla nao enviada.")


def key_down(key: str) -> None:
    _require_focus()
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
    _require_focus()
    pydirectinput.keyDown(key)
    try:
        time.sleep(hold_seconds)
    finally:
        # mesmo se o sleep for interrompido por uma excecao, a tecla sobe
        pydirectinput.keyUp(key)


def release_all() -> None:
    """Solta TODAS as teclas atualmente seguradas por este processo. Chame
    no finally do loop principal, na tecla de panico, ao fechar o app e no
    atexit."""
    with _lock:
        for key in list(_held_keys):
            try:
                pydirectinput.keyUp(key)
            except Exception:
                pass
        _held_keys.clear()


def ensure_only(key: str | None) -> None:
    """Garante que, dentre um grupo mutuamente exclusivo (ex: W vs S), apenas
    `key` (ou nenhuma, se None) esteja pressionada."""
    if key is not None:
        _require_focus()
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
