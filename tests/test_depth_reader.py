"""depth_reader: leitura da PROFUNDIDADE e do prompt 'Parar nesta profundidade'.

Tudo aqui roda contra capturas REAIS do jogo (tests/fixtures/depth, prompt,
linha), rotuladas olhando as imagens. Os modelos de digito sao gerados pelas
proprias fixtures (tools/build_depth_templates.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from fishingbot import depth_reader as dr

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_depth_templates as builder  # noqa: E402


def _read(path: Path) -> np.ndarray:
    img = cv2.imread(str(path))
    assert img is not None, path
    return img


def _expected(path: Path) -> int | None:
    m = re.match(r"v(\d+)", path.name)
    return int(m.group(1)) if m else None


DEPTH_FILES = sorted((FIXTURES / "depth").glob("*.png"))
PROMPT_E = sorted((FIXTURES / "prompt").glob("e_*.png"))
PROMPT_NOT_E = (sorted((FIXTURES / "prompt").glob("x_*.png")) + sorted((FIXTURES / "prompt").glob("peixe_*.png"))
                + sorted((FIXTURES / "prompt").glob("nada_*.png")) + sorted((FIXTURES / "pulling_state").glob("*.png")))


# -- valor da profundidade ---------------------------------------------------------------------------------

@pytest.mark.parametrize("path", DEPTH_FILES, ids=lambda p: p.stem)
def test_le_a_profundidade_das_capturas_reais(path):
    reading = dr.read_depth(_read(path))
    assert reading.value == _expected(path), reading.reason


def test_cobertura_das_fixtures_inclui_areia_e_agua_e_o_fundo():
    names = " ".join(p.name for p in DEPTH_FILES)
    assert "none_areia" in names and "none_escuro" in names and "none_arremessando" in names
    assert "f_" in names, "precisa de casos '(fundo)'"
    assert len({_expected(p) for p in DEPTH_FILES if _expected(p) is not None}) >= 7


def test_modelos_feitos_so_com_o_linha_leem_a_profundidade_nunca_vista(monkeypatch):
    """Teste FORA DA AMOSTRA: digitos aprendidos so do numero grande do LINHA
    classificam corretamente a caixa PROFUNDIDADE (que o modelo nunca viu)."""
    samples: dict[str, list] = {}
    for path in sorted((FIXTURES / "linha").glob("linha_*.png")):
        text = "".join(re.match(r"linha_(\d+)_(\d)_", path.name).groups())
        glyphs = builder._digit_glyphs(_read(path))
        assert len(glyphs) == len(text), path.name
        for ch, g in zip(text, glyphs):
            samples.setdefault(ch, []).append(dr.normalize_glyph(g.mask))
    assert set(samples) == set("0123456789")
    models = {k: np.mean(v, axis=0) for k, v in samples.items()}

    checked = 0
    for path in DEPTH_FILES:
        want = _expected(path)
        if want is None:
            continue
        glyphs = builder._digit_glyphs(dr.to_reference(_read(path)))
        got = ""
        for g in glyphs:
            scores = sorted((float(np.abs(dr.normalize_glyph(g.mask) - t).mean()), k) for k, t in models.items())
            assert scores[0][0] <= dr.MAX_DIST and scores[1][0] - scores[0][0] >= dr.MIN_MARGIN, path.name
            got += scores[0][1]
        assert got == str(want), path.name
        checked += 1
    assert checked >= 14


def _paste_digit(base: np.ndarray, digit_row: np.ndarray, shift: int) -> np.ndarray:
    """Cola em `base` o digito de `digit_row` deslocado `shift` px (negativo = esquerda)."""
    glyph = builder._digit_glyphs(digit_row)[0]
    out = base.copy()
    x0, x1 = glyph.x - 1, glyph.x + glyph.w + 1
    out[:, x0 + shift:x1 + shift] = digit_row[:, x0:x1]
    return out


@pytest.mark.parametrize("digits,expected", [("12", 12), ("10", 10), ("25", 25), ("125", 125)])
def test_numeros_de_varios_digitos_sintetizados(digits, expected):
    """SINTETICO (a gravacao so tinha profundidade de 1 digito): cola digitos
    reais da captura, com o passo de 12 px da fonte monoespacada, antes do 'm'."""
    rows = {d: _read(next((FIXTURES / "depth").glob(f"v{d}_0*.png"))) for d in set(digits)
            if list((FIXTURES / "depth").glob(f"v{d}_0*.png"))}
    if len(rows) != len(set(digits)):
        pytest.skip("sem fixture real de algum digito (ex.: 0 so existe em 'v0')")
    img = rows[digits[-1]].copy()
    for i, d in enumerate(reversed(digits[:-1]), start=1):
        img = _paste_digit(img, rows[d], -12 * i)
    assert dr.read_depth(img).value == expected


def test_zero_a_esquerda_de_digito_tambem_le():
    one = _read(next((FIXTURES / "depth").glob("v1_0*.png")))
    zero = _read(next((FIXTURES / "depth").glob("v0_0*.png")))
    assert dr.read_depth(_paste_digit(zero, one, -12)).value == 10


def test_sem_o_m_da_unidade_nao_le():
    img = _read(next((FIXTURES / "depth").glob("v4_0*.png")))
    img[:, 236:] = 0          # apaga o 'm' (fica em x~243)
    r = dr.read_depth(img)
    assert r.value is None and "m" in r.reason


@pytest.mark.parametrize("make", [
    lambda: np.zeros((43, 270, 3), np.uint8),
    lambda: np.full((43, 270, 3), 255, np.uint8),
    lambda: np.random.default_rng(1).integers(0, 255, (43, 270, 3), dtype=np.uint8),
    lambda: np.random.default_rng(2).integers(200, 255, (43, 270, 3), dtype=np.uint8),
], ids=["preto", "branco", "ruido", "ruido_claro"])
def test_lixo_nunca_vira_numero(make):
    assert dr.read_depth(make()).value is None


def test_leitura_nunca_devolve_numero_errado_em_outras_resolucoes():
    """Abaixo de 1080p a leitura pode falhar (None) -- e e aceitavel, o bot nao
    aperta nada -- mas NUNCA pode devolver um numero diferente do real."""
    for scale in (0.85, 0.75, 0.667, 0.5):
        for path in DEPTH_FILES:
            img = _read(path)
            small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            got = dr.read_depth(small).value
            assert got in (None, _expected(path)), f"{path.name} @{scale}: leu {got}"


@pytest.mark.parametrize("scale", [1.0, 4 / 3, 2.0])
def test_le_em_1080p_e_acima(scale):
    for path in DEPTH_FILES:
        img = _read(path)
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        assert dr.read_depth(img).value == _expected(path), f"{path.name} @{scale}"


# -- prompt 'Parar nesta profundidade' ----------------------------------------------------------------

@pytest.mark.parametrize("path", PROMPT_E, ids=lambda p: p.stem)
def test_prompt_do_E_e_detectado(path):
    assert dr.depth_prompt_visible(_read(path)) is True


@pytest.mark.parametrize("path", PROMPT_NOT_E, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_outros_paineis_e_cenario_nao_sao_o_prompt_do_E(path):
    """Inclui 'X Parar de pescar', 'PEIXE Calmo/Puxando forte', areia e escuro:
    apertar E nesses casos faria outra coisa no jogo."""
    assert dr.depth_prompt_visible(_read(path)) is False


def test_prompt_tem_margem_grande_entre_positivos_e_negativos():
    pos = min(min(dr.depth_prompt_score(_read(p))) for p in PROMPT_E)
    neg = max(min(dr.depth_prompt_score(_read(p))) for p in PROMPT_NOT_E)
    assert pos >= 0.95 and neg <= 0.65 and dr.PROMPT_MIN_SCORE - neg > 0.2


def test_prompt_em_resolucao_menor_nao_da_falso_positivo():
    for scale in (0.75, 0.5):
        for p in PROMPT_NOT_E:
            small = cv2.resize(_read(p), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            assert dr.depth_prompt_visible(small) is False


# -- modelos versionados -----------------------------------------------------------------------------------

def test_modelos_versionados_sao_os_gerados_das_fixtures():
    """Se alguem editar uma fixture sem regerar os modelos (ou o contrario), falha."""
    current = Path(builder.OUTPUT).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == builder.render(), "rode: venv\\Scripts\\python tools\\build_depth_templates.py"


def test_todos_os_digitos_tem_modelo():
    digits, m, prompt = dr._templates()
    assert set(digits) == set("0123456789")
    assert m.shape == (18, 12) and prompt.shape == (43, 270) and prompt.sum() > 200


def test_digitos_longe_demais_um_do_outro_nao_formam_numero():
    """'1' e '2' separados por 3 celulas nao sao '12': so o digito colado ao 'm' conta."""
    one = _read(next((FIXTURES / "depth").glob("v1_0*.png")))
    two = _read(next((FIXTURES / "depth").glob("v2_0*.png")))
    assert dr.read_depth(_paste_digit(two, one, -36)).value == 2
