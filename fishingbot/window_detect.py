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
    import win32api
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


# Padroes usados pra identificar a janela do jogo em si (nao o launcher, nao
# splash screens). O executavel real do jogo dentro do FiveM costuma se
# chamar algo como 'FiveM_b3751_GTAProcess.exe' (o numero de build varia).
_PROCESS_NAME_HINTS = ("gtaprocess",)
_TITLE_HINTS = ("fivem",)


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


def _get_process_name(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
            return path.rsplit("\\", 1)[-1]
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def find_fivem_window() -> WindowInfo | None:
    """Procura entre as janelas visiveis de topo a que pertence ao processo
    do jogo FiveM (nao o launcher). Entre candidatas, escolhe a de maior
    area visivel (a janela do jogo em si, nao alguma janela auxiliar
    pequena). Retorna None se nao encontrar nenhuma.

    Com o logger em nivel DEBUG (--debug), quando NENHUMA candidata bate,
    loga todas as janelas visiveis com titulo nao-vazio (titulo + nome do
    processo) que o EnumWindows encontrou -- serve pra descobrir rapido se o
    titulo/processo real da janela do FiveM e diferente do que os hints
    (_PROCESS_NAME_HINTS / _TITLE_HINTS) esperam, em vez de ficar tentando
    adivinhar as cegas."""
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
        proc_name_lc = proc_name.lower()
        title_lc = title.lower()

        if debug_on and title.strip():
            seen.append(f"titulo={title!r} processo={proc_name!r}")

        matches_process = any(h in proc_name_lc for h in _PROCESS_NAME_HINTS)
        matches_title = any(h in title_lc for h in _TITLE_HINTS) and title.strip() != ""

        if not (matches_process or matches_title):
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
                          f"_TITLE_HINTS={_TITLE_HINTS}. Janelas visiveis com titulo: {seen}")
            else:
                log.debug("[debug] find_fivem_window: nenhuma janela visivel com titulo "
                          "encontrada nesta varredura (EnumWindows nao achou nada com texto)")
        return None

    # Prioriza match por PROCESSO (mais confiavel que titulo, que muda com o
    # nome do servidor). Entre elas, pega a de maior area.
    by_process = [c for c in candidates if any(h in c.process_name.lower() for h in _PROCESS_NAME_HINTS)]
    pool = by_process if by_process else candidates
    pool.sort(key=lambda c: c.width * c.height, reverse=True)
    if debug_on and len(candidates) > 1:
        log.debug(f"[debug] find_fivem_window: {len(candidates)} candidata(s) batida(s), "
                  f"escolhida a maior: {pool[0].title!r} {pool[0].width}x{pool[0].height}")
    return pool[0]


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
