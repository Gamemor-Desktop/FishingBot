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
    Janela mudou de tamanho/posicao/DPI -> CALIBRANDO (recalculo, barato)
    Minigame nao aparece / desapareceu -> AGUARDANDO_MINIGAME

Sobre o estado CALIBRANDO: so aparece (e so regrava o config.json) quando a
janela encontrada e DIFERENTE da ultima calibracao salva em
%LOCALAPPDATA%\FishingBot\config.json (posicao/tamanho/DPI). Se for a mesma
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

from . import config_store, fishing_logic, manual_control
from .app_state import AppState, SharedState
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
WINDOW_CHECK_INTERVAL = 1.0   # com que frequencia reconferir se a janela mudou


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
        self._thread = threading.Thread(target=self._run, name="FishingBotController", daemon=True)
        self._thread.start()

    def request_quit(self) -> None:
        self.shared.update(quit_requested=True, user_wants_running=False)
        self._stop_event.set()

    # -- loop principal ---------------------------------------------------

    def _run(self) -> None:
        shared = self.shared
        shared.set_state(AppState.INICIALIZANDO)
        time.sleep(0.3)  # so pra a mensagem aparecer na UI antes de sumir rapido demais

        while not self._stop_event.is_set():
            if not shared.user_wants_running:
                shared.set_state(AppState.PARADO)
                time.sleep(POLL_WHEN_STOPPED)
                continue

            window = self._find_window_blocking()
            if window is None:
                continue  # _find_window_blocking ja tratou o estado/espera

            regions, keybinds, timings = self._calibrate(window)

            self._automation_loop(window, regions, keybinds, timings)
            # _automation_loop so retorna quando a janela sumiu, mudou de
            # forma que precise recalibrar, ou o usuario mandou parar -- o
            # loop externo trata cada caso reiniciando do ponto certo.

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

    def _automation_loop(self, window: WindowInfo, regions: dict, keybinds: dict, timings: dict) -> None:
        """Roda ciclos de pesca ate a janela sumir/mudar ou o usuario parar."""
        shared = self.shared
        last_window_check = 0.0

        # Simulacao de teclado vai sempre pra janela em primeiro plano do
        # sistema -- garante que e o FiveM logo ao entrar na automacao, em
        # vez de descobrir so quando uma tecla nao chega no jogo.
        if not self.dry_run and not is_foreground(window.hwnd):
            if not bring_to_foreground(window.hwnd):
                log.warning(
                    "FiveM nao esta em primeiro plano e nao consegui trazer ele pra frente "
                    "automaticamente -- clique na janela do jogo, senao as teclas simuladas "
                    "podem nao chegar nele."
                )

        with mss.mss() as sct:
            while not self._stop_event.is_set() and shared.user_wants_running:
                now = time.time()
                if now - last_window_check >= WINDOW_CHECK_INTERVAL:
                    last_window_check = now
                    if not window_still_valid(window):
                        log.info("Janela do FiveM sumiu -> voltando a procurar")
                        return
                    refreshed = refresh_window_rect(window)
                    if refreshed is None:
                        return
                    if (refreshed.left, refreshed.top, refreshed.width, refreshed.height) != \
                       (window.left, window.top, window.width, window.height):
                        log.info("Janela do FiveM mudou de posicao/tamanho -> recalibrando")
                        window = refreshed
                        regions, keybinds, timings = self._calibrate(window)

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

                    confirmed = manual_control.wait_for_confirmation(
                        lambda: shared.should_stop_cycle() or not window_still_valid(window)
                    )
                    if not confirmed:
                        return
                    log.info("ENTER recebido -> retomando automacao pra proxima pescaria.")
                else:
                    time.sleep(0.5)
