"""
Garante uma unica instancia do FishingBot por sessao do Windows. Duas
instancias mandariam teclas em dobro pro jogo (S+W+ESPACO duplicados) e
brigariam pelo mesmo hook de teclado.

Usa um mutex nomeado do Windows: o proprio sistema libera ele quando o
processo termina (inclusive em crash), entao nunca fica "preso".
"""
from __future__ import annotations

import sys

MUTEX_NAME = "Local\\FishingBot_SingleInstance"
_ERROR_ALREADY_EXISTS = 183

_handles: list[int] = []  # mantem o mutex vivo ate o processo acabar


def acquire(name: str = MUTEX_NAME) -> bool:
    """True se esta e a unica instancia (mutex criado agora). False se ja
    existe outra rodando. Fora do Windows sempre retorna True."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

    handle = kernel32.CreateMutexW(None, False, name)
    last_error = ctypes.get_last_error()
    if not handle:
        # nao conseguiu nem criar o mutex: nao bloqueia o uso por causa disso
        return True
    if last_error == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handles.append(handle)
    return True


def show_already_running_message() -> None:
    """Aviso visivel mesmo no .exe --windowed (que nao tem console)."""
    if sys.platform != "win32":
        print("O FishingBot ja esta aberto.")
        return
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        "O FishingBot ja esta aberto. Feche a outra janela antes de abrir de novo.",
        "FishingBot",
        0x40,  # MB_ICONINFORMATION
    )
