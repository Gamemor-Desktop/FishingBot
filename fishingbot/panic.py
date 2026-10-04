"""
Tecla de panico global (padrao F10, configuravel em keybinds.panic_key).

Funciona via hook global do Windows (biblioteca `keyboard`), entao responde
mesmo com o FiveM em primeiro plano -- que e justamente quando voce precisa
dela. Em qualquer estado (minigame, puxando, esperando ENTER, dry-run), ela
chama o callback registrado, que para o bot e solta todas as teclas.

Diferente do ENTER de manual_control.py, esta tecla NUNCA e ignorada.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

try:
    import keyboard
except Exception:  # pragma: no cover - so acontece fora do Windows/sem a lib
    keyboard = None

log = logging.getLogger("fishingbot")

_lock = threading.Lock()
_installed_key: str | None = None


def install(callback: Callable[[], None], key: str = "f10") -> bool:
    """Registra o hook uma unica vez (idempotente). Retorna True se a tecla
    de panico esta ativa depois da chamada."""
    global _installed_key
    if keyboard is None:
        log.warning("Biblioteca 'keyboard' indisponivel -- a tecla de panico NAO vai funcionar.")
        return False
    with _lock:
        if _installed_key is not None:
            return True

        def _on_press(_event=None) -> None:
            log.warning(f"TECLA DE PANICO ({key.upper()}) acionada")
            try:
                callback()
            except Exception:
                log.exception("Falha no callback da tecla de panico")

        try:
            keyboard.on_press_key(key, _on_press, suppress=False)
        except Exception:
            log.exception(
                f"Nao foi possivel registrar a tecla de panico ({key}) -- se o jogo "
                "estiver rodando como administrador, rode o FishingBot como "
                "administrador tambem. Use o botao PARAR como alternativa."
            )
            return False
        _installed_key = key
        log.info(f"Tecla de panico registrada: {key.upper()}")
        return True


def active_key() -> str | None:
    """A tecla de panico efetivamente registrada, ou None se nao funciona."""
    return _installed_key
