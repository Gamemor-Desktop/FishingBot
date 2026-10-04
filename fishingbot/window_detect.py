"""
Deteccao da janela do FiveM no Windows: DPI awareness, localizar o processo/
janela certos e obter a area util (client area) em pixels fisicos de tela --
o mesmo espaco de coordenadas que o mss usa pra capturar a tela e que o
pydirectinput usa pra simular teclado/mouse.

So funciona no Windows (usa pywin32). Em outro SO, as funcoes retornam None/
lancam ImportError de forma controlada, pra permitir pelo menos importar o
modulo (uteis para lint/teste) sem quebrar tudo.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    import win32gui
    import win32process
    import win32con

log = logging.getLogger("fishingbot")


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    # client area em coordenadas ABSOLUTAS de tela (pixels fisicos)
    left: int
    top: int
    width: int
    height: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)


# Como identificar a janela do jogo em si (nao o launcher, nao splash
# screens, e principalmente nao um navegador/terminal com "FiveM" no titulo):
# o executavel real do jogo dentro do FiveM se chama algo como
# 'FiveM_b3751_GTAProcess.exe' (o numero de build varia), e a janela dele usa
# a classe 'grcWindow' (a mesma do GTA V). Basta UM dos dois bater -- o titulo
# NAO conta: ele muda com o servidor e qualquer aba de navegador pode ter
# "FiveM" nele, e o bot manda teclas pra janela que ele achar.
_PROCESS_NAME_HINTS = ("gtaprocess",)
_WINDOW_CLASSES = ("grcwindow",)


def is_game_window(process_name: str, class_name: str) -> bool:
    """True se (processo, classe) identificam a janela do jogo FiveM/GTA."""
    proc = (process_name or "").lower()
    cls = (class_name or "").lower()
    return any(h in proc for h in _PROCESS_NAME_HINTS) or cls in _WINDOW_CLASSES


def setup_dpi_awareness() -> None:
    """Marca o PROPRIO processo como DPI-aware (per-monitor v2 quando
    disponivel). Isso faz GetWindowRect/GetClientRect e a captura de tela
    (mss) concordarem em pixels FISICOS, independente da escala configurada
    no Windows (100%, 125%, 150%...). Chamar isso uma unica vez, o mais cedo
    possivel na inicializacao do programa, antes de qualquer consulta de
    janela ou captura de tela."""
    if not IS_WINDOWS:
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE_V2 (-4) quando disponivel (Win10 1703+)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        # Fallback: PROCESS_PER_MONITOR_DPI_AWARE (2), Win8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        # Fallback antigo: DPI aware "system-wide", Vista+
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_dpi_scale_percent(hwnd: int | None = None) -> int:
    """Retorna a escala de DPI aproximada em % (100, 125, 150...) do monitor
    onde a janela esta, ou do monitor primario se hwnd nao for dado."""
    if not IS_WINDOWS:
        return 100
    try:
        if hwnd:
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        else:
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
        return round(dpi / 96 * 100)
    except Exception:
        return 100


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _get_process_name(hwnd: int) -> str:
    """Nome do .exe dono da janela, ou "" se nao der pra ler. Usa
    QueryFullProcessImageNameW, que funciona com PROCESS_QUERY_LIMITED_INFORMATION
    (o GetModuleFileNameEx anterior exige QUERY_INFORMATION + VM_READ, que um
    processo elevado -- ex: FiveM rodando como administrador -- nega)."""
    if not IS_WINDOWS:
        return ""
    try:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.rsplit("\\", 1)[-1]
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return ""


def find_fivem_window() -> WindowInfo | None:
    """Procura entre as janelas visiveis de topo a que e a do jogo FiveM
    (processo *GTAProcess* ou classe 'grcWindow', ver is_game_window; o
    titulo nunca conta). Entre candidatas, escolhe a de maior area (a janela
    do jogo em si, nao alguma janela auxiliar pequena). Retorna None se nao
    encontrar nenhuma.

    Com o logger em nivel DEBUG (--debug), quando NENHUMA candidata bate,
    loga todas as janelas visiveis com titulo nao-vazio (titulo + processo +
    classe) que o EnumWindows encontrou -- serve pra descobrir rapido se o
    processo/classe real da janela do FiveM e diferente do que
    _PROCESS_NAME_HINTS / _WINDOW_CLASSES esperam."""
    if not IS_WINDOWS:
        return None

    candidates: list[WindowInfo] = []
    debug_on = log.isEnabledFor(logging.DEBUG)
    seen: list[str] = [] if debug_on else None

    def _enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.IsIconic(hwnd):  # minimizada
            return
        title = win32gui.GetWindowText(hwnd) or ""
        proc_name = _get_process_name(hwnd)
        try:
            class_name = win32gui.GetClassName(hwnd) or ""
        except Exception:
            class_name = ""

        if debug_on and title.strip():
            seen.append(f"titulo={title!r} processo={proc_name!r} classe={class_name!r}")

        if not is_game_window(proc_name, class_name):
            return

        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            # GetClientRect retorna (0,0,w,h) relativo a propria janela;
            # precisamos converter o canto superior esquerdo pra coordenadas
            # absolutas de tela.
            (abs_left, abs_top) = win32gui.ClientToScreen(hwnd, (left, top))
            width = right - left
            height = bottom - top
        except Exception:
            if debug_on:
                log.debug(f"[debug] find_fivem_window: titulo={title!r} processo={proc_name!r} "
                          f"bateu no nome mas GetClientRect/ClientToScreen falhou -- ignorada")
            return

        if width < 200 or height < 150:
            # janela auxiliar/tooltip, nao a janela principal do jogo
            if debug_on:
                log.debug(f"[debug] find_fivem_window: titulo={title!r} processo={proc_name!r} "
                          f"bateu no nome mas e pequena demais ({width}x{height}) -- ignorada "
                          f"(minimo 200x150)")
            return

        candidates.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                process_name=proc_name,
                left=abs_left,
                top=abs_top,
                width=width,
                height=height,
            )
        )

    win32gui.EnumWindows(_enum_handler, None)

    if not candidates:
        if debug_on:
            if seen:
                log.debug(f"[debug] find_fivem_window: nenhuma candidata bateu em "
                          f"_PROCESS_NAME_HINTS={_PROCESS_NAME_HINTS} / "
                          f"_WINDOW_CLASSES={_WINDOW_CLASSES}. Janelas visiveis com titulo: {seen}")
            else:
                log.debug("[debug] find_fivem_window: nenhuma janela visivel com titulo "
                          "encontrada nesta varredura (EnumWindows nao achou nada com texto)")
        return None

    # Entre as candidatas, pega a de maior area.
    candidates.sort(key=lambda c: c.width * c.height, reverse=True)
    if debug_on and len(candidates) > 1:
        log.debug(f"[debug] find_fivem_window: {len(candidates)} candidata(s) batida(s), "
                  f"escolhida a maior: {candidates[0].title!r} "
                  f"{candidates[0].width}x{candidates[0].height}")
    return candidates[0]


def describe_foreground() -> str:
    """Texto curto de quem esta com o foco agora ("Claude [claude.exe]"), pra
    explicar nos logs/na tela POR QUE o jogo foi considerado 'sem foco'."""
    if not IS_WINDOWS:
        return "?"
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "nenhuma janela"
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        proc = _get_process_name(hwnd) or "?"
        return f"{title[:40] or '(sem titulo)'} [{proc}]"
    except Exception:
        return "?"


def is_foreground(hwnd: int) -> bool:
    """True se `hwnd` e a janela em primeiro plano (a que recebe teclado)
    agora mesmo. Simulacao de teclado (pydirectinput/SendInput) sempre vai
    pra janela em primeiro plano do SISTEMA, nao pra uma janela especifica
    -- se o FiveM nao estiver em primeiro plano na hora de apertar uma
    tecla, a tecla vai pra QUALQUER OUTRA COISA que estiver em foco (o
    proprio terminal do bot, por exemplo) e o jogo nunca recebe nada."""
    if not IS_WINDOWS:
        return False
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def bring_to_foreground(hwnd: int) -> bool:
    """Tenta trazer `hwnd` pra primeiro plano (foco de teclado), restaurando
    se estiver minimizada. O Windows normalmente BLOQUEIA um processo em
    segundo plano de roubar o foco do usuario (pra evitar apps chatos) --
    o workaround padrao, documentado pela propria Microsoft, e "anexar"
    temporariamente a fila de input da nossa thread a fila de input da
    thread dona da janela em primeiro plano atual (AttachThreadInput),
    chamar SetForegroundWindow, e desanexar em seguida. Retorna True se a
    janela realmente ficou em primeiro plano depois da tentativa (o
    Windows pode recusar mesmo assim em alguns casos)."""
    if not IS_WINDOWS:
        return False
    try:
        if is_foreground(hwnd):
            return True

        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)

        attached_fg = False
        attached_target = False
        if fg_thread and fg_thread != current_thread:
            attached_fg = bool(ctypes.windll.user32.AttachThreadInput(current_thread, fg_thread, True))
        if target_thread and target_thread != current_thread:
            attached_target = bool(ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, True))

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached_fg:
                ctypes.windll.user32.AttachThreadInput(current_thread, fg_thread, False)
            if attached_target:
                ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, False)

        return is_foreground(hwnd)
    except Exception:
        return False


def window_exists(hwnd: int) -> bool:
    """A janela ainda existe e esta visivel (minimizada CONTA como existente:
    o FiveM se minimiza sozinho ao perder o foco)."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(win32gui.IsWindow(hwnd)) and bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


def is_minimized(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False


def client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """(left, top, width, height) da area util em coordenadas de tela, ou None."""
    if not IS_WINDOWS:
        return None
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        abs_left, abs_top = win32gui.ClientToScreen(hwnd, (left, top))
        return abs_left, abs_top, right - left, bottom - top
    except Exception:
        return None


def find_minimized_game_window() -> int | None:
    """hwnd da janela do jogo se ela existe mas esta MINIMIZADA (o FiveM se
    minimiza ao perder o foco; find_fivem_window ignora janelas minimizadas)."""
    if not IS_WINDOWS:
        return None
    found: list[int] = []

    def _enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.IsIconic(hwnd):
            return
        try:
            class_name = win32gui.GetClassName(hwnd) or ""
        except Exception:
            class_name = ""
        if is_game_window(_get_process_name(hwnd), class_name):
            found.append(hwnd)

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception:
        return None
    return found[0] if found else None


def window_still_valid(info: WindowInfo) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(win32gui.IsWindow(info.hwnd)) and win32gui.IsWindowVisible(info.hwnd) and not win32gui.IsIconic(info.hwnd)
    except Exception:
        return False


def refresh_window_rect(info: WindowInfo) -> WindowInfo | None:
    """Releitura da posicao/tamanho atual da mesma janela (hwnd), pra
    detectar se ela foi movida, redimensionada ou fechada. Retorna None se a
    janela nao existe mais."""
    if not IS_WINDOWS or not window_still_valid(info):
        return None
    try:
        left, top, right, bottom = win32gui.GetClientRect(info.hwnd)
        (abs_left, abs_top) = win32gui.ClientToScreen(info.hwnd, (left, top))
        width = right - left
        height = bottom - top
        if width < 200 or height < 150:
            return None
        return WindowInfo(
            hwnd=info.hwnd,
            title=win32gui.GetWindowText(info.hwnd) or info.title,
            process_name=info.process_name,
            left=abs_left,
            top=abs_top,
            width=width,
            height=height,
        )
    except Exception:
        return None
