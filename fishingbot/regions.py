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


# Fracoes derivadas dos pixels absolutos medidos em 1920x1080.
# Historico e evidencia de cada valor: docs/calibracao.md.
DEFAULT_FRACTIONS = {
    # bolinha vermelha + peixinho da fase de mordida
    "hook_zone": _frac(756, 528, 252, 108),
    # linha 3 do HUD (y=528): "PEIXE Calmo/Puxando forte", "X Parar de pescar" ou
    # "E Parar nesta profundidade" -- o mesmo lugar muda de conteudo conforme a fase.
    # Recalibrada em 14/09/2026.
    "pulling_state": _frac(24, 528, 270, 43),
    # linha 2 do HUD (y=477): "PROFUNDIDADE  N m". Medida na gravacao de 04/10/2026
    # (docs/calibracao.md); lida por depth_reader.py.
    "depth_row": _frac(24, 477, 270, 43),
}

# Cores HSV sao independentes de resolucao -- nao precisam de fracao.
# Cada bloco abaixo foi medido em capturas reais; o porque dos numeros, as
# datas e as evidencias estao em docs/calibracao.md (os testes em tests/ usam
# as mesmas capturas como fixtures, entao ajustar um limiar e validado).
DEFAULT_COLORS = {
    # Fisgada: pixels BRILHANTES (V>=200) + forma de disco da bolinha. A roupa do
    # personagem tem o mesmo matiz mas e escura (V<=173) e irregular.
    "hook_zone": {
        "lower": [0, 120, 200],
        "upper": [15, 255, 255],
        # bolinha = componente conexo (areas em px na resolucao de referencia,
        # escalam com a janela), quase quadrado e bem preenchido
        "ball_min_area": 80,
        "ball_max_area": 300,
        "ball_aspect_min": 0.75,
        "ball_aspect_max": 1.33,
        "ball_min_fill": 0.70,
        # proporcao de brilhantes com o peixe alinhado (so bolinha ~0.0054;
        # bolinha + peixe ~0.0255)
        "hit_min_ratio": 0.014,
        # frames CONSECUTIVOS acima de hit_min_ratio antes de apertar ESPACO
        "hit_confirm_frames": 2,
    },
    # "Calmo": azul-marinho escuro. V<=48 e S<=140 separam a caixa do fundo do jogo.
    "pulling_gray": {"lower": [95, 50, 15], "upper": [120, 140, 48]},
    # "Puxando forte": vinho escuro; o matiz fica dos DOIS lados do wrap 0/179
    # conforme a luz do jogo, por isso duas faixas.
    "pulling_red": {
        "ranges": [
            ([135, 35, 20], [179, 200, 150]),
            ([0, 30, 70], [15, 200, 255]),
        ],
    },
    # Aviso "X Parar de pescar": texto vermelho vivo + o X branco da tecla.
    # Aparece junto da mordida, nao logo apos lancar.
    "stop_prompt": {
        "red_ranges": [([0, 140, 170], [8, 255, 255]), ([172, 140, 170], [179, 255, 255])],
        "red_x_from": 0.15,      # faixa horizontal do texto vermelho
        "red_x_to": 0.75,
        "x_key_to": 0.22,        # faixa onde fica a tecla 'X'
        "min_red": 0.02,
        "min_white": 0.003,
        "max_white": 0.05,
    },
    # Texto branco do painel: independe do fundo (a caixa e translucida). Sem
    # texto nao ha painel; texto + fundo escuro + sem vermelho = "Calmo".
    "pulling_text": {
        "x_start": 0.40,        # so a metade direita (onde fica o texto de estado)
        "white_min_v": 225,
        "white_max_s": 40,
        "dark_max_v": 110,
        "min_ratio": 0.01,
        "calm_min_ratio": 0.02,
        "calm_max_ratio": 0.20,
        "calm_min_near_dark": 0.8,
        "calm_max_red_ratio": 0.05,
    },
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
