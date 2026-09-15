"""
Regioes do minigame, expressas como FRACOES da area util (client area) da
janela do FiveM -- nao como pixels absolutos. Isso e o que permite o bot
funcionar em qualquer resolucao/proporcao/escala sem editar coordenadas:
a gente calcula uma vez em pixels (via calibracao ao vivo, feita direto na
tela do usuario) e guarda como fracao (0.0 a 1.0) da largura/altura da
janela do jogo. Depois, pra qualquer resolucao, e so multiplicar de novo.

Isso assume que a interface do FiveM (que e renderizada via NUI/CEF, tipo um
navegador embutido) escala proporcionalmente com o tamanho da janela do jogo
-- o que e o comportamento padrao de UIs baseadas em CSS/viewport, e bate
com o fato de o painel estar sempre ancorado no canto superior esquerdo em
qualquer resolucao. Se algum dia isso nao bater (ex: HUD com tamanho fixo em
pixels independente da resolucao), os valores abaixo precisam ser
recalibrados -- veja README.md.

REFERENCE_WINDOW = resolucao em que as fracoes abaixo foram medidas
originalmente (1920x1080, calibrado ao vivo na tela do usuario).
"""
from __future__ import annotations

from dataclasses import dataclass

REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080


def _frac(x: float, y: float, w: float, h: float) -> dict:
    return {
        "fx": x / REFERENCE_WIDTH,
        "fy": y / REFERENCE_HEIGHT,
        "fw": w / REFERENCE_WIDTH,
        "fh": h / REFERENCE_HEIGHT,
    }


# Fracoes derivadas dos pixels absolutos calibrados em 1920x1080 (veja o
# projeto fivem_fishing_bot original / README para a origem de cada valor).
DEFAULT_FRACTIONS = {
    # bolinha vermelha + peixinho da fase BELISCOU (estimado a partir de
    # screenshots do usuario, resolucao 1920x1080)
    "hook_zone": _frac(756, 528, 252, 108),
    # linha "PEIXE" (Calmo / Puxando forte) do painel de puxar o peixe --
    # recalibrado a partir de screenshot real 1920x1080 em 14/09/2026 (caixa
    # com borda vermelha vai de x=24..293, y=528..570; a calibracao anterior
    # (16,403,208,33) estava ~125px mais alta que a caixa real, por isso o
    # bot nunca via o painel de verdade e so dava match por coincidencia)
    "pulling_state": _frac(24, 528, 270, 43),
    # numero de distancia na linha "LINHA" (opcional, so log/OCR)
    "distance_ocr": _frac(95, 322, 70, 30),
}

# Cores HSV sao independentes de resolucao -- nao precisam de fracao.
DEFAULT_COLORS = {
    "hook_zone": {
        "lower": [0, 120, 150],
        "upper": [15, 255, 255],
        "bite_min_ratio": 0.0045,
        "hit_min_ratio": 0.014,
    },
    # "Calmo": recalibrado com base em screenshot real da caixa em estado
    # calmo (14/09/2026) -- a caixa NAO e cinza neutro, e um azul-marinho
    # escuro (fundo RGB~(19..25, 23..30, 30..35) -> H~106-109 no OpenCV,
    # borda RGB~(26..27, 46..47, 71..72) -> H~106, S~160). O range antigo
    # (S ate 60) cortava fora praticamente toda a caixa real (S real ~90-162),
    # por isso so batia ~1% da area em vez da caixa inteira.
    "pulling_gray": {"lower": [95, 50, 15], "upper": [120, 200, 100]},
    # "Puxando forte": recalibrado com base em pixels reais da caixa (fundo
    # marrom-avermelhado escuro RGB~(31..85, 25..41, 34..44), borda
    # RGB~(145..158, 54..58, 47..51)). No HSV de 0-179 graus do OpenCV essa
    # cor cai perto de H=135-179 (vermelho "escuro"/vinho, do lado que faz
    # wrap com H=0), bem longe da faixa antiga (H=0-25, vermelho-laranja
    # vivo) -- por isso o range antigo nunca batia com a caixa de verdade.
    "pulling_red": {"lower": [135, 35, 20], "upper": [179, 200, 150]},
}


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

    def as_roi(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


def compute_region(window_left: int, window_top: int, window_width: int, window_height: int,
                    fractions: dict) -> Region:
    x = window_left + round(fractions["fx"] * window_width)
    y = window_top + round(fractions["fy"] * window_height)
    w = max(1, round(fractions["fw"] * window_width))
    h = max(1, round(fractions["fh"] * window_height))
    return Region(x, y, w, h)


def compute_all_regions(window_left: int, window_top: int, window_width: int, window_height: int,
                         fractions_override: dict | None = None) -> dict:
    """Calcula todas as regioes (em pixels absolutos de tela) para a janela
    atual do jogo. fractions_override permite sobrescrever qualquer uma das
    fracoes padrao (ex: apos uma recalibracao manual, ou ajuste fino salvo
    pelo usuario em config.json)."""
    fractions = {**DEFAULT_FRACTIONS}
    if fractions_override:
        for key, value in fractions_override.items():
            if key in fractions:
                fractions[key] = {**fractions[key], **value}

    return {
        name: compute_region(window_left, window_top, window_width, window_height, frac)
        for name, frac in fractions.items()
    }
