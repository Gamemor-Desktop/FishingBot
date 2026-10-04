"""
Ponto de entrada do FishingBot. Isto e o que o PyInstaller empacota como
FishingBot.exe.

Uso: FishingBot.exe [--dry-run] [--debug]
    --dry-run  nao envia nenhuma tecla de verdade, so mostra na interface o
               que estaria fazendo. Util pra testar deteccao/calibracao sem
               risco de mexer numa pescaria real.
    --debug    ativa log detalhado (proporcoes de cor calculadas a cada
               frame) e salva screenshots das regioes capturadas em
               %LOCALAPPDATA%\\FishingBot\\debug\\. Use junto com --dry-run
               pra diagnosticar problemas de deteccao (ex: bot nao consegue
               puxar/dar linha) sem risco.
"""
from __future__ import annotations

import argparse
import atexit
import logging
import logging.handlers
import sys
import threading

from fishingbot import config_store, debug_tools, diagnostics, input_sim, single_instance
from fishingbot.gui import run_app
from fishingbot.window_detect import setup_dpi_awareness


LOG_MAX_BYTES = 2_000_000   # cada arquivo de log; com --debug uma sessao longa passa disso
LOG_BACKUPS = 3             # fishingbot.log.1 .. .3 (os mais antigos sao descartados)


def _setup_logging(debug: bool = False) -> None:
    handlers: list[logging.Handler] = []
    try:
        log_path = config_store.config_dir() / "fishingbot.log"
        handlers.append(logging.handlers.RotatingFileHandler(
            log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"))
    except OSError:
        pass  # pasta somente leitura/bloqueada: o bot roda mesmo assim, sem arquivo de log
    if sys.stdout is not None:  # no .exe --windowed nao existe stdout
        handlers.append(logging.StreamHandler(sys.stdout))
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,  # configuracao deterministica mesmo se algo ja tiver registrado handlers
    )


def _install_crash_hooks() -> None:
    """Excecao nao tratada (qualquer thread): vai pro log com traceback e
    solta todas as teclas -- no .exe --windowed o stderr nao existe, entao
    sem isso o erro some sem deixar rastro."""
    log = logging.getLogger("fishingbot")

    def _main_hook(exc_type, exc, tb):
        log.critical("Excecao nao tratada", exc_info=(exc_type, exc, tb))
        input_sim.release_all()

    def _thread_hook(args):
        log.critical(f"Excecao nao tratada na thread {args.thread.name if args.thread else '?'}",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        input_sim.release_all()

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook


def main() -> None:
    if sys.platform != "win32":
        print("FishingBot so funciona no Windows (depende de pywin32/DirectInput).")
        sys.exit(1)

    # Duas instancias mandariam teclas em dobro pro jogo.
    if not single_instance.acquire():
        single_instance.show_already_running_message()
        sys.exit(1)

    # DPI-aware o mais cedo possivel, antes de qualquer coisa que consulte
    # janelas ou capture a tela.
    setup_dpi_awareness()

    parser = argparse.ArgumentParser(description="FishingBot - automacao de pesca no FiveM")
    parser.add_argument("--dry-run", action="store_true",
                         help="nao envia teclas de verdade, so simula/loga")
    parser.add_argument("--debug", action="store_true",
                         help="loga proporcoes de cor por frame e salva screenshots das "
                              "regioes em %%LOCALAPPDATA%%\\FishingBot\\debug\\")
    args = parser.parse_args()

    _setup_logging(debug=args.debug)
    _install_crash_hooks()
    diagnostics.install_ring_handler()  # ultimas linhas de log pro pacote de diagnostico
    atexit.register(input_sim.release_all)  # ultima rede de seguranca ao sair
    if args.debug:
        debug_tools.enable()
    logging.getLogger("fishingbot").info(f"FishingBot iniciando (dry_run={args.dry_run}, debug={args.debug})")

    run_app(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
