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
import logging
import os
import sys

from fishingbot import config_store, debug_tools
from fishingbot.gui import run_app
from fishingbot.window_detect import setup_dpi_awareness


def _setup_logging(debug: bool = False) -> None:
    log_dir = config_store.config_dir()
    log_path = log_dir / "fishingbot.log"
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    if sys.platform != "win32":
        print("FishingBot so funciona no Windows (depende de pywin32/DirectInput).")
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
    if args.debug:
        debug_tools.enable()
    logging.getLogger("fishingbot").info(f"FishingBot iniciando (dry_run={args.dry_run}, debug={args.debug})")

    run_app(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
