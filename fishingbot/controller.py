"""
A maquina de estados principal do aplicativo (nao confundir com os estados
internos de UM ciclo de pesca, que ficam em fishing_logic.py). Roda numa
thread de fundo, separada da interface grafica, pra tela nunca travar.

Fluxo (bate com o pedido original):

    INICIALIZANDO
        -> PROCURANDO_FIVEM
        -> DETECTANDO_JANELA
        -> CALIBRANDO
        -> AGUARDANDO_MINIGAME
        -> AUTOMACAO
        -> CAPTURA_CONCLUIDA
        -> AGUARDANDO_CONFIRMACAO_MANUAL -> (volta pra AGUARDANDO_MINIGAME)

Sobre AGUARDANDO_CONFIRMACAO_MANUAL: pegar o peixe capturado no chao e
corta-lo/processa-lo ainda NAO e automatizado -- o bot fica parado nesse
estado depois de cada captura, sem lançar a vara de novo sozinho, ate o
jogador apertar ENTER (unico gatilho de teclado usado pelo usuario, tratado
em manual_control.py e ignorado em qualquer outro estado).

Quedas de condicao voltam pro estado apropriado em vez de encerrar o
programa:
    FiveM fechado / janela sumiu -> PROCURANDO_FIVEM
    Janela mudou de tamanho/posicao -> CALIBRANDO (recalculo, barato)
    Minigame nao aparece / desapareceu -> AGUARDANDO_MINIGAME

Seguranca (nada disso depende do ciclo de pesca "se comportar"):
    - Um watchdog (thread) confere a janela a cada 0.5s DURANTE o ciclo,
      nao so entre ciclos, e aborta o ciclo se ela sumir ou mudar.
    - Toda tecla enviada passa pela guarda de foco (input_sim): se o FiveM
      nao esta em primeiro plano, nada e enviado e o bot para (estado ERRO).
    - Qualquer excecao nao prevista cai no supervisor de _run: loga o
      traceback, solta todas as teclas e vai pra ERRO em vez de matar a
      thread em silencio.
    - Tecla de panico global (panic.py) e shutdown() soltam tudo.

Sobre o estado CALIBRANDO: so aparece (e so regrava o config.json) quando a
janela encontrada e DIFERENTE da ultima calibracao salva em
%LOCALAPPDATA%/FishingBot/config.json (posicao/tamanho/DPI). Se for a mesma
janela de uma execucao anterior, pula direto pra AGUARDANDO_MINIGAME. Isso
NAO significa que as regioes ficam "congeladas" de uma vez por todas -- elas
continuam sendo recalculadas a partir da janela atual a cada execucao (e uma
formula, custa nada), so o passo visivel/log e a regravacao do arquivo que
sao pulados quando nada mudou. Isso preserva a seguranca: se por acaso a
janela NAO estiver de fato identica (por exemplo o FiveM abrir num
monitor/posicao diferente), o bot detecta a diferenca e recalibra do jeito
certo em vez de usar coordenadas desatualizadas.
"""
from __future__ import annotations

import logging
import threading
import time

import mss

from . import config_store, fishing_logic, input_sim, manual_control, panic
from .app_state import ERRO_STATUS_TEXT, AppState, SharedState
from .input_sim import FocusLostError
from .regions import compute_all_regions
from .window_detect import (
    WindowInfo,
    bring_to_foreground,
    find_fivem_window,
    get_dpi_scale_percent,
    is_foreground,
    refresh_window_rect,
    setup_dpi_awareness,
    window_still_valid,
)

log = logging.getLogger("fishingbot")

POLL_WHEN_STOPPED = 0.2      # intervalo de poll quando o usuario nao mandou rodar
POLL_LOOKING_FOR_FIVEM = 0.7  # intervalo entre tentativas de achar a janela
WATCHDOG_INTERVAL = 0.5       # com que frequencia o watchdog reconfere a janela
FOCUS_WAIT_TIMEOUT = 20.0     # quanto esperar o usuario focar o jogo ao iniciar
FOCUS_RETRY_INTERVAL = 2.0    # de quanto em quanto tempo tentar trazer o jogo pra frente


def check_window_health(window: WindowInfo,
                        still_valid=window_still_valid,
                        refresh=refresh_window_rect) -> str | None:
    """None se a janela segue igual; senao o motivo pra abortar o ciclo.
    (Funcoes injetaveis so pra poder testar sem o Windows.)"""
    if not still_valid(window):
        return "A janela do FiveM sumiu"
    refreshed = refresh(window)
    if refreshed is None:
        return "A janela do FiveM sumiu"
    if (refreshed.left, refreshed.top, refreshed.width, refreshed.height) != \
       (window.left, window.top, window.width, window.height):
        return "A janela do FiveM mudou de posicao/tamanho"
    return None


class _WindowWatchdog:
    """Thread que confere a janela do jogo a cada WATCHDOG_INTERVAL enquanto
    um ciclo de pesca roda (que pode durar minutos sem olhar pra janela) e
    pede aborto via SharedState.request_abort se ela sumir ou mudar."""

    def __init__(self, shared: SharedState, window: WindowInfo,
                 interval: float = WATCHDOG_INTERVAL, check=check_window_health):
        self._shared = shared
        self._window = window
        self._interval = interval
        self._check = check
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="FishingBotWatchdog", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                reason = self._check(self._window)
            except Exception:
                log.exception("Falha no watchdog da janela")
                reason = "Falha ao conferir a janela do FiveM"
            if reason:
                log.info(f"Watchdog: {reason} -> abortando o ciclo atual")
                self._shared.request_abort(reason)
                return


class Controller:
    def __init__(self, shared: SharedState, dry_run: bool = False):
        self.shared = shared
        self.dry_run = dry_run
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.cfg = config_store.load_config()

    def start(self) -> None:
        setup_dpi_awareness()
        # Registra o listener global de ENTER uma unica vez -- e usado la
        # na frente pra confirmar o passo manual entre uma pesca e outra
        # (ver manual_control.py).
        manual_control.ensure_listener()
        panic.install(self.panic, self.cfg["keybinds"].get("panic_key", "f10"))
        self._thread = threading.Thread(target=self._run, name="FishingBotController", daemon=True)
        self._thread.start()

    def request_quit(self) -> None:
        self.shared.update(quit_requested=True, user_wants_running=False)
        self._stop_event.set()

    def panic(self) -> None:
        """Parada de emergencia (tecla de panico): para o bot e solta tudo.
        Pode ser chamada de qualquer thread, em qualquer estado."""
        key = (panic.active_key() or self.cfg["keybinds"].get("panic_key", "f10")).upper()
        self.shared.fail(f"PARADA DE EMERGENCIA ({key}) -- bot parado. Aperte INICIAR pra retomar.")
        input_sim.release_all()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Encerramento limpo: pede pra parar, espera a thread soltar as
        teclas (ate `timeout`) e solta tudo de novo por garantia."""
        self.request_quit()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        input_sim.release_all()

    # -- loop principal ---------------------------------------------------

    def _run(self) -> None:
        shared = self.shared
        shared.set_state(AppState.INICIALIZANDO)
        time.sleep(0.3)  # so pra a mensagem aparecer na UI antes de sumir rapido demais

        while not self._stop_event.is_set():
            if not shared.user_wants_running:
                # Um erro/panico fica visivel ate o usuario apertar INICIAR
                # de novo -- nao pode ser apagado por um "Parado" generico.
                err = shared.snapshot()["error_message"]
                if err:
                    shared.set_state(AppState.ERRO, ERRO_STATUS_TEXT)
                else:
                    shared.set_state(AppState.PARADO)
                time.sleep(POLL_WHEN_STOPPED)
                continue

            # Supervisor: nada que acontecer dentro de um ciclo pode matar
            # esta thread em silencio (a interface continuaria mostrando
            # "Aguardando pesca..." com o bot morto, e tecla presa).
            try:
                self._run_once()
            except FocusLostError as exc:
                log.warning(f"Foco perdido: {exc}")
                input_sim.release_all()
                shared.fail("O FiveM perdeu o foco -- bot parado por seguranca. "
                            "Volte pro jogo e aperte INICIAR.")
            except Exception as exc:
                log.exception("Erro inesperado no controlador -- parando o bot")
                input_sim.release_all()
                shared.fail(f"Erro inesperado ({type(exc).__name__}: {exc}). "
                            f"Veja o fishingbot.log. Aperte INICIAR pra tentar de novo.")

    def _run_once(self) -> None:
        """Uma passada completa: achar janela -> calibrar -> automacao. Volta
        quando a janela some/muda ou o usuario manda parar; o loop externo
        reinicia do ponto certo."""
        self.shared.clear_abort()
        window = self._find_window_blocking()
        if window is None:
            return  # _find_window_blocking ja tratou o estado/espera

        regions, keybinds, timings = self._calibrate(window)
        self._automation_loop(window, regions, keybinds, timings)

    # -- fases --------------------------------------------------------------

    def _find_window_blocking(self) -> WindowInfo | None:
        """Fica em PROCURANDO_FIVEM ate achar a janela, o usuario mandar
        parar, ou o app fechar. Retorna a janela encontrada, ou None se saiu
        por parada/fechamento (o chamador deve voltar pro topo do loop)."""
        shared = self.shared
        shared.set_state(AppState.PROCURANDO_FIVEM)
        shared.update(fivem_found=False, calibration_ok=False)

        search_start = time.time()
        attempts = 0

        while not self._stop_event.is_set() and shared.user_wants_running:
            attempts += 1
            window = find_fivem_window()
            if window is not None:
                elapsed = time.time() - search_start
                shared.update(fivem_found=True, window_title=window.title)
                shared.set_state(AppState.DETECTANDO_JANELA,
                                  f"FiveM encontrado: {window.title!r}")
                log.info(f"FiveM encontrado apos {elapsed:.1f}s ({attempts} tentativa(s)) -- "
                         f"processo={window.process_name!r} titulo={window.title!r} "
                         f"{window.width}x{window.height} em ({window.left},{window.top})")
                time.sleep(0.2)
                return window
            time.sleep(POLL_LOOKING_FOR_FIVEM)

        return None

    def _calibrate(self, window: WindowInfo) -> tuple[dict, dict, dict]:
        shared = self.shared

        dpi = get_dpi_scale_percent(window.hwnd)
        is_same_as_last = not config_store.needs_recalibration(
            self.cfg, window.width, window.height, window.left, window.top, dpi
        )

        if is_same_as_last:
            # Mesma janela (posicao/tamanho/DPI) da ultima calibracao salva
            # -- pula o estado CALIBRANDO e a regravacao do config.json.
            shared.set_state(AppState.DETECTANDO_JANELA, "Calibracao anterior reaproveitada.")
        else:
            shared.set_state(AppState.CALIBRANDO)

        # As regioes SEMPRE sao recalculadas a partir da janela atual (e so
        # uma formula fracao->pixel, nao tem custo) -- isso e o que garante
        # que, se a janela na verdade nao for identica, o bot ainda funciona
        # certo em vez de usar coordenadas desatualizadas.
        regions = compute_all_regions(
            window.left, window.top, window.width, window.height,
            fractions_override=self.cfg.get("fractions_override"),
        )

        if is_same_as_last:
            log.info(f"Janela igual a ultima calibracao conhecida "
                     f"({window.width}x{window.height} em ({window.left},{window.top}), "
                     f"DPI {dpi}%) -> reaproveitando, sem regravar config.json")
        else:
            config_store.update_last_calibration(self.cfg, window.width, window.height,
                                                   window.left, window.top, dpi)
            log.info(f"Calibrado para janela {window.width}x{window.height} "
                     f"em ({window.left},{window.top}), DPI {dpi}%")
            for name, region in regions.items():
                log.info(f"  regiao '{name}': x={region.x} y={region.y} "
                         f"w={region.w} h={region.h}")

        shared.update(
            resolution=f"{window.width}x{window.height}",
            dpi_scale=f"{dpi}%",
            calibration_ok=True,
            last_calibrated_at=time.time(),
        )

        keybinds = self.cfg["keybinds"]
        timings = self.cfg["timings"]
        return regions, keybinds, timings

    def _wait_for_game_focus(self, window: WindowInfo) -> bool:
        """Leva o FiveM pra primeiro plano antes de qualquer tecla. Clicar em
        INICIAR deixa o foco na janela do bot, entao primeiro tentamos trazer
        o jogo pra frente sozinhos e, se o Windows recusar, esperamos
        FOCUS_WAIT_TIMEOUT segundos o usuario clicar no jogo. Retorna False se
        o usuario mandou parar; levanta FocusLostError se estourou o tempo."""
        shared = self.shared
        deadline = time.monotonic() + FOCUS_WAIT_TIMEOUT
        next_try = 0.0
        while not self._stop_event.is_set() and shared.user_wants_running:
            if is_foreground(window.hwnd):
                return True
            now = time.monotonic()
            if now >= deadline:
                raise FocusLostError("Nao consegui trazer o FiveM pra frente e ninguem clicou nele.")
            if now >= next_try:
                next_try = now + FOCUS_RETRY_INTERVAL
                if bring_to_foreground(window.hwnd):
                    return True
                shared.set_state(AppState.DETECTANDO_JANELA,
                                  "Clique na janela do FiveM pra comecar a pescar...")
            time.sleep(0.25)
        return False

    def _automation_loop(self, window: WindowInfo, regions: dict, keybinds: dict, timings: dict) -> None:
        """Roda ciclos de pesca ate a janela sumir/mudar ou o usuario parar."""
        shared = self.shared

        # Simulacao de teclado vai sempre pra janela em primeiro plano do
        # sistema -- so comecamos com o FiveM de fato em foco, e a guarda de
        # foco (input_sim) bloqueia qualquer tecla se ele perder o foco depois.
        if not self.dry_run:
            if not self._wait_for_game_focus(window):
                return
            input_sim.set_focus_guard(lambda: is_foreground(window.hwnd))

        watchdog = _WindowWatchdog(shared, window)
        watchdog.start()
        try:
            with mss.mss() as sct:
                while not self._stop_event.is_set() and shared.user_wants_running:
                    if shared.should_stop_cycle():
                        return  # watchdog pediu aborto (janela sumiu/mudou)

                    shared.set_state(AppState.AGUARDANDO_MINIGAME)
                    completed = fishing_logic.do_one_cast(sct, regions, keybinds, timings, shared,
                                                            self.dry_run, hwnd=window.hwnd)

                    if shared.should_stop_cycle():
                        return

                    if completed:
                        time.sleep(0.8)  # deixa o texto "Peixe capturado!" visivel um instante

                        # Etapa manual (nao automatizada por enquanto): o
                        # jogador precisa pegar o peixe no chao e corta-lo/
                        # processa-lo antes de estar pronto pra uma nova
                        # pescaria. O bot NAO inicia sozinho aqui -- fica
                        # parado ate o jogador apertar ENTER (o unico gatilho
                        # de teclado usado pelo usuario; ignorado em qualquer
                        # outro estado, ver manual_control.py).
                        shared.set_state(AppState.AGUARDANDO_CONFIRMACAO_MANUAL)
                        log.info("Peixe capturado -- aguardando o jogador pegar/cortar o peixe "
                                 "e apertar ENTER pra continuar.")

                        confirmed = manual_control.wait_for_confirmation(shared.should_stop_cycle)
                        if not confirmed:
                            return
                        log.info("ENTER recebido -> retomando automacao pra proxima pescaria.")
                    else:
                        time.sleep(0.5)
        finally:
            watchdog.stop()
            input_sim.set_focus_guard(None)
            input_sim.release_all()
