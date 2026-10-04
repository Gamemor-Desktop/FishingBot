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
    # Fisgada. Antes era so "proporcao de pixels vermelho-laranja" com limiar
    # absoluto, mas a roupa do personagem (hoodie listrado) tem as mesmas cores
    # e gera 0.005-0.023 de ruido -- MAIOR que a propria bolinha (~0.0057) --,
    # entao a mordida "era detectada" por coincidencia e o ESPACO disparava sem
    # peixe (visto em log real). Medido em 123 capturas reais (--debug,
    # 03/10/2026): 4 tem a bolinha, 119 nao.
    #   - bolinha/peixe: BRILHANTES (V ~ 221-231); roupa: V <= 173.
    #   - bolinha: disco compacto 14x14 (area ~155-165, preenchimento >= 0.79).
    #     Roupa: manchas finas/irregulares (preenchimento <= 0.65).
    # Por isso: V >= 200 na mascara + checagem de forma da bolinha. Nas 123
    # capturas isso acha 4/4 bolinhas e 0/119 falsos; ruido restante <= 0.001
    # de proporcao, contra 0.0054 (so bolinha) e 0.0255 (bolinha + peixe).
    "hook_zone": {
        "lower": [0, 120, 200],
        "upper": [15, 255, 255],
        # bolinha = componente conexo com area em [min, max] px (na resolucao
        # de referencia 1920x1080 -- escala com a janela), quase quadrado e
        # bem preenchido
        "ball_min_area": 80,
        "ball_max_area": 300,
        "ball_aspect_min": 0.75,
        "ball_aspect_max": 1.33,
        "ball_min_fill": 0.70,
        # proporcao de pixels brilhantes quando o peixe vermelho alinha com a
        # bolinha (so bolinha ~0.0054; bolinha + peixe ~0.0255)
        "hit_min_ratio": 0.014,
        # frames CONSECUTIVOS acima de hit_min_ratio antes de apertar ESPACO
        "hit_confirm_frames": 2,
    },
    # "Calmo": recalibrado com base em screenshot real da caixa em estado
    # calmo (14/09/2026) -- a caixa NAO e cinza neutro, e um azul-marinho
    # escuro (fundo RGB~(19..25, 23..30, 30..35) -> H~106-109 no OpenCV,
    # borda RGB~(26..27, 46..47, 71..72) -> H~106, S~160). O range antigo
    # (S ate 60) cortava fora praticamente toda a caixa real (S real ~90-162),
    # por isso so batia ~1% da area em vez da caixa inteira.
    #
    # V e S apertados de novo em 15/09/2026, com base em screenshots de
    # debug de uma sessao real: depois que a caixa "Calmo" some de vez (peixe
    # ja fora d'agua), a regiao capturada fica so com o FUNDO azul-marinho
    # escuro do jogo por tras -- e esse fundo (V~51-68, S~145-223) batia
    # TAMBEM com o range antigo (V ate 100, S ate 200), dando ratio=1.0 igual
    # a caixa de verdade. Resultado: o bot nunca via a leitura cair abaixo do
    # limiar depois que o peixe saia da agua, e ficava segurando a tecla
    # (pull_key) por dezenas de segundos (visto num log real: 49s seguidos)
    # ate estourar timeout. A caixa real tem V mediano ~33 (bem mais escura
    # que o fundo, que fica ~51-68) e S mediano ~116 (mais baixo que o fundo,
    # ~145-223) -- por isso apertar V<=48 e S<=140 corta o fundo fora mas
    # ainda cobre ~88% da caixa real (testado contra os screenshots dessa
    # sessao, bem acima do min_ratio=0.3 usado em classify_pull_state).
    "pulling_gray": {"lower": [95, 50, 15], "upper": [120, 140, 48]},
    # "Puxando forte": recalibrado com base em pixels reais da caixa (fundo
    # marrom-avermelhado escuro RGB~(31..85, 25..41, 34..44), borda
    # RGB~(145..158, 54..58, 47..51)). No HSV de 0-179 graus do OpenCV essa
    # cor cai perto de H=135-179 (vermelho "escuro"/vinho, do lado que faz
    # wrap com H=0), bem longe da faixa antiga (H=0-25, vermelho-laranja
    # vivo) -- por isso o range antigo nunca batia com a caixa de verdade.
    #
    # 15/09/2026: descoberto (com screenshots de debug de uma sessao real)
    # que a MESMA caixa "Puxando forte" pode renderizar com H perto de 0
    # (media ~8, visto numa sessao com luz ambiente do jogo mais clara/
    # quente) em vez de perto de 179 (media ~161, sessao anterior, luz mais
    # escura) -- e o range de cima (H 135-179) so cobre um dos dois lados.
    # Resultado: com H~8 o ratio ficava 0.0 o tempo todo, o painel de puxar
    # "nunca aparecia" (aviso as 3.0s) mesmo com a caixa visivel na tela, e o
    # bot desistia do lance sem nunca ter puxado nada. Como H e circular
    # (0 e 179 sao vizinhos), a correcao e cobrir os dois lados do wrap com
    # duas faixas em vez de uma so -- ver "ranges" abaixo e
    # vision.hsv_mask_multi. Validado contra 4 screenshots reais de
    # "Puxando forte" (2 de cada sessao/iluminacao): ratio 0.77-0.92 nos
    # dois casos, sem gerar falso positivo nos screenshots de fundo vazio/
    # outros paineis dessas mesmas sessoes.
    "pulling_red": {
        "ranges": [
            ([135, 35, 20], [179, 200, 150]),
            ([0, 30, 70], [15, 200, 255]),
        ],
    },
    # Aviso "X Parar de pescar": aparece enquanto a linha esta na agua, ou seja,
    # e o sinal de que a pesca COMECOU depois do lance. Texto vermelho vivo +
    # o "X" branco da tecla, a esquerda. Medido em 18 capturas rotuladas
    # (4 com o aviso, em 4 fundos diferentes): vermelho 0.030-0.039 e branco do
    # X 0.0063 em todas; o painel "Puxando forte" tem vermelho (0.045) mas sem
    # o X, e a cerca branca tem branco (0.61) mas sem vermelho.
    "stop_prompt": {
        "red_ranges": [([0, 140, 170], [8, 255, 255]), ([172, 140, 170], [179, 255, 255])],
        "red_x_from": 0.15,      # faixa horizontal do texto vermelho
        "red_x_to": 0.75,
        "x_key_to": 0.22,        # faixa onde fica a tecla 'X'
        "min_red": 0.02,
        "min_white": 0.003,
        "max_white": 0.05,
    },
    # Texto branco do painel ("Calmo", "Puxando forte", "Quase fora d'agua"):
    # independe do fundo, ao contrario da cor da caixa, que e TRANSLUCIDA e
    # muda com o cenario atras. Medido em 103 capturas reais (03/10/2026): o
    # painel tem texto branco na metade direita em 3.5%-10% da area (27% sobre
    # fundo claro), cercado de fundo escuro; o aviso "Parar de pescar" (texto
    # vermelho), a agua, a madeira e o fundo cinza tem ~0%; a cerca branca tem
    # 9%-59% mas SEM fundo escuro em volta (near_dark 0.14-0.22).
    # Usos (ver fishing_logic.classify_pull_state):
    #   - sem texto (< min_ratio) nao ha painel, mesmo que a cor "bata"
    #     (elimina 'Parar de pescar' sobre agua escura lido como Calmo e a
    #     madeira lida como Puxando forte);
    #   - "Calmo" translucido sobre fundo marrom/claro, que a cor nao pega: texto
    #     + fundo escuro em volta + nenhum vermelho = Calmo. Antes isso fazia o
    #     bot achar que o painel tinha sumido e declarar "peixe capturado" 1-3s
    #     depois do ESPACO, com o peixe ainda na linha.
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
