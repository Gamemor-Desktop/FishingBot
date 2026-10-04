"""
Gera fishingbot/depth_templates.py (modelos dos digitos, do 'm' e do prompt
'[E] Parar nesta profundidade') a partir das capturas rotuladas em
tests/fixtures/. Reproduzivel: o teste tests/test_depth_reader.py roda isto e
confere que o arquivo versionado e igual ao gerado.

Fontes de amostras (todas capturas reais do jogo):
  tests/fixtures/linha/linha_<int>_<dec>_<ms>.png   numero grande do LINHA (ex.
        linha_89_5_... = "89,5"): mesma fonte e quase o mesmo tamanho da
        profundidade, e traz todos os digitos 0-9
  tests/fixtures/depth/v<valor>*.png                caixa PROFUNDIDADE com o valor
        no nome (v4f_a_... = "4 m (fundo)"): digitos no tamanho exato + o 'm'
  tests/fixtures/prompt/e_*.png                     linha 3 com o prompt do E

Uso:   venv\\Scripts\\python tools\\build_depth_templates.py          (grava)
       venv\\Scripts\\python tools\\build_depth_templates.py --check  (so confere)
"""
from __future__ import annotations

import base64
import re
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fishingbot import depth_reader as dr  # noqa: E402

OUTPUT = ROOT / "fishingbot" / "depth_templates.py"
FIXTURES = ROOT / "tests" / "fixtures"
PROMPT_KEEP = 0.6   # pixel entra no modelo do prompt se estiver branco em >= 60% das amostras


def _encode(arr_u8: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", arr_u8)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _digit_glyphs(img: np.ndarray) -> list:
    """Glifos de altura de digito na metade direita (virgula e textos pequenos ficam de fora)."""
    mask = dr.white_mask(img[:, dr.VALUE_X0:])
    return dr.extract_glyphs(mask, dr.VALUE_X0, dr.DIGIT_H)


def collect(fixtures: Path = FIXTURES) -> tuple[dict, list, list]:
    digits: dict[str, list] = defaultdict(list)
    m_samples: list = []
    prompt_masks: list = []

    for path in sorted((fixtures / "linha").glob("linha_*.png")):
        text = "".join(re.match(r"linha_(\d+)_(\d)_", path.name).groups())
        glyphs = _digit_glyphs(cv2.imread(str(path)))
        if len(glyphs) != len(text):
            raise SystemExit(f"{path.name}: esperava {len(text)} digitos ({text}), achei {len(glyphs)}")
        for ch, g in zip(text, glyphs):
            digits[ch].append(dr.normalize_glyph(g.mask))

    for path in sorted((fixtures / "depth").glob("v*.png")):
        text = re.match(r"v(\d+)", path.name).group(1)
        img = dr.to_reference(cv2.imread(str(path)))
        glyphs = _digit_glyphs(img)
        if len(glyphs) != len(text):
            raise SystemExit(f"{path.name}: esperava {len(text)} digitos ({text}), achei {len(glyphs)}")
        for ch, g in zip(text, glyphs):
            digits[ch].append(dr.normalize_glyph(g.mask))
        small = [g for g in dr.extract_glyphs(dr.white_mask(img[:, dr.VALUE_X0:]), dr.VALUE_X0, (8, 12)) if g.w >= 8]
        if not small:
            raise SystemExit(f"{path.name}: nao achei o 'm'")
        m_samples.append(dr.normalize_glyph(small[-1].mask))

    for path in sorted((fixtures / "prompt").glob("e_*.png")):
        prompt_masks.append((dr.white_mask(dr.to_reference(cv2.imread(str(path)))) > 0).astype(np.float32))

    missing = sorted(set("0123456789") - set(digits))
    if missing or not m_samples or not prompt_masks:
        raise SystemExit(f"faltam amostras: digitos {missing}, m={len(m_samples)}, prompt={len(prompt_masks)}")
    return digits, m_samples, prompt_masks


def render(fixtures: Path = FIXTURES) -> str:
    digits, m_samples, prompt_masks = collect(fixtures)
    mean = lambda xs: np.mean(xs, axis=0)  # noqa: E731
    to_u8 = lambda a: np.clip(np.rint(a * 255), 0, 255).astype(np.uint8)  # noqa: E731
    lines = [
        '"""GERADO por tools/build_depth_templates.py -- NAO edite a mao.',
        "",
        "Modelos (PNG em base64) dos digitos 0-9, do 'm' da unidade e do prompt",
        "'[E] Parar nesta profundidade', tirados de capturas reais do jogo",
        '(tests/fixtures/). Para regerar: venv\\\\Scripts\\\\python tools\\\\build_depth_templates.py',
        '"""',
        "",
        "DIGITS = {",
    ]
    for ch in sorted(digits):
        lines.append(f'    "{ch}": "{_encode(to_u8(mean(digits[ch])))}",  # {len(digits[ch])} amostras')
    lines += ["}", "", f'M = "{_encode(to_u8(mean(m_samples)))}"  # {len(m_samples)} amostras', ""]
    prompt = (mean(prompt_masks) >= PROMPT_KEEP).astype(np.uint8) * 255
    lines += [f'PROMPT = "{_encode(prompt)}"  # {len(prompt_masks)} amostras', ""]
    return "\n".join(lines)


def main() -> int:
    source = render()
    if "--check" in sys.argv:
        current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else ""
        if current != source:
            print("depth_templates.py esta desatualizado: rode tools/build_depth_templates.py")
            return 1
        print("depth_templates.py esta em dia")
        return 0
    OUTPUT.write_text(source, encoding="utf-8", newline="\n")
    print(f"gravado {OUTPUT} ({len(source)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
