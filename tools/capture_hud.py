"""
Grava o HUD de pesca do FiveM pra eu (e os testes) poderem ver como a
PROFUNDIDADE aparece. NAO envia nenhuma tecla: voce joga normalmente.

Uso (no prompt de comando, na pasta do projeto):

    venv\\Scripts\\python tools\\capture_hud.py

1. Rode o comando. Ele espera o FiveM ficar em primeiro plano (ate 60 s).
2. Volte pro jogo, lance a vara e deixe a linha afundar ate ~25 m
   (ou mais), aperte E ("Parar nesta profundidade") e, se quiser, espere a
   mordida e a puxada. A gravacao dura 90 s.
3. Os arquivos ficam em %LOCALAPPDATA%\\FishingBot\\hud_capture\\<data_hora>\\

Opcoes:  --seconds N   duracao (padrao 90)      --now   nao esperar o foco
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import mss  # noqa: E402
import numpy as np  # noqa: E402

from fishingbot import config_store  # noqa: E402
from fishingbot.regions import REFERENCE_HEIGHT, REFERENCE_WIDTH, compute_all_regions  # noqa: E402
from fishingbot.window_detect import find_fivem_window, is_foreground, setup_dpi_awareness  # noqa: E402

ROI_INTERVAL = 0.1     # 10 quadros/s da caixa do painel (270x43 px: pequenos)
CONTEXT_EVERY = 5      # a cada 5 quadros, tambem a coluna inteira do HUD (mostra o layout)
# coluna do HUD na resolucao de referencia (x, y, largura, altura)
CONTEXT_REF = (0, 380, 480, 340)


def _grab(sct, left: int, top: int, width: int, height: int) -> np.ndarray:
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--now", action="store_true", help="nao esperar o FiveM ficar em foco")
    args = ap.parse_args()

    setup_dpi_awareness()
    print("Procurando a janela do FiveM...")
    window = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        window = find_fivem_window()
        if window is not None and (args.now or is_foreground(window.hwnd)):
            break
        time.sleep(0.3)
    else:
        print("Nao achei o FiveM em primeiro plano em 60 s. Abra o jogo e rode de novo.")
        return 1

    regions = compute_all_regions(window.left, window.top, window.width, window.height)
    roi = regions["pulling_state"]          # a caixa onde aparece PEIXE / PROFUNDIDADE
    sx, sy = window.width / REFERENCE_WIDTH, window.height / REFERENCE_HEIGHT
    cx, cy, cw, ch = CONTEXT_REF
    ctx = (window.left + round(cx * sx), window.top + round(cy * sy), round(cw * sx), round(ch * sy))

    out = config_store.config_dir() / "hud_capture" / time.strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "info.txt").write_text(
        f"janela {window.width}x{window.height} em ({window.left},{window.top})\n"
        f"roi (caixa PEIXE/PROFUNDIDADE): x={roi.x} y={roi.y} w={roi.w} h={roi.h}\n"
        f"contexto (coluna do HUD): x={ctx[0]} y={ctx[1]} w={ctx[2]} h={ctx[3]}\n", encoding="utf-8")

    print(f"\nGRAVANDO por {args.seconds:.0f} s em {out}")
    print("Agora: lance a vara, deixe afundar ate ~25 m, aperte E, e (se quiser) espere a mordida.\n")
    start = time.monotonic()
    n = 0
    with mss.MSS() as sct:
        while True:
            t = time.monotonic() - start
            if t >= args.seconds:
                break
            ms = int(t * 1000)
            cv2.imwrite(str(out / f"roi_{ms:06d}ms.png"), _grab(sct, roi.x, roi.y, roi.w, roi.h))
            if n % CONTEXT_EVERY == 0:
                cv2.imwrite(str(out / f"ctx_{ms:06d}ms.png"), _grab(sct, *ctx))
            n += 1
            time.sleep(max(0.0, ROI_INTERVAL - ((time.monotonic() - start) - t)))
    print(f"Pronto: {n} quadros em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
