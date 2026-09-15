"""
Logica do minigame de pesca em si (a mesma mecanica do projeto
fivem_fishing_bot original), agora parametrizada por regioes DINAMICAS
(calculadas a partir da janela do jogo a cada ciclo, veja regions.py) em vez
de coordenadas fixas num config.json. Cada funcao tambem verifica
periodicamente shared.should_stop_cycle() pra poder abortar rapido e soltar
as teclas se o usuario apertar "Parar" no meio de um ciclo.
"""
from __future__ import annotations

import logging
import time

import mss

from . import debug_tools, input_sim, vision, window_detect
from .app_state import AppState, SharedState
from .regions import DEFAULT_COLORS, Region

log = logging.getLogger("fishingbot")


def _hook_zone_ratio(sct: mss.mss, roi: Region) -> float:
    frame = vision.grab(sct, roi.as_roi())
    colors = DEFAULT_COLORS["hook_zone"]
    mask = vision.hsv_mask(frame, colors["lower"], colors["upper"])
    ratio = vision.pixel_ratio(mask)
    debug_tools.save_roi("hook_zone", frame, mask)
    return ratio


def wait_for_bite(sct: mss.mss, regions: dict, shared: SharedState, dry_run: bool,
                   timeout_seconds: float) -> bool:
    hz = regions["hook_zone"]
    colors = DEFAULT_COLORS["hook_zone"]
    start = time.time()
    confirm = 0
    while time.time() - start < timeout_seconds:
        if shared.should_stop_cycle():
            return False
        ratio = _hook_zone_ratio(sct, hz)
        debug_tools.log_ratio("hook_zone_bite", ratio, colors["bite_min_ratio"])
        if ratio >= colors["bite_min_ratio"]:
            confirm += 1
            if confirm >= 2:
                return True
        else:
            confirm = 0
        time.sleep(0.02)
    return False


def run_timing_minigame(sct: mss.mss, regions: dict, keybinds: dict, shared: SharedState,
                         dry_run: bool, timeout_seconds: float) -> bool:
    hz = regions["hook_zone"]
    colors = DEFAULT_COLORS["hook_zone"]
    start = time.time()
    while time.time() - start < timeout_seconds:
        if shared.should_stop_cycle():
            return False
        ratio = _hook_zone_ratio(sct, hz)
        debug_tools.log_ratio("hook_zone_hit", ratio, colors["hit_min_ratio"])
        if ratio >= colors["hit_min_ratio"]:
            log.info(f"Peixe alinhado (ratio={ratio:.4f}) -> ESPACO")
            if not dry_run:
                input_sim.tap(keybinds["space_key"], hold_seconds=0.04)
            return True
        time.sleep(0.008)
    log.warning("Timeout no timing_minigame")
    return False


def classify_pull_state(sct: mss.mss, regions: dict) -> str | None:
    roi = regions["pulling_state"]
    frame = vision.grab(sct, roi.as_roi())
    gray = DEFAULT_COLORS["pulling_gray"]
    red = DEFAULT_COLORS["pulling_red"]
    gray_mask = vision.hsv_mask(frame, gray["lower"], gray["upper"])
    red_mask = vision.hsv_mask(frame, red["lower"], red["upper"])
    gray_ratio = vision.pixel_ratio(gray_mask)
    red_ratio = vision.pixel_ratio(red_mask)
    min_ratio = 0.3
    debug_tools.save_roi("pulling_state", frame)
    debug_tools.log_ratio("pulling_state", max(gray_ratio, red_ratio), min_ratio,
                           extra=f"gray={gray_ratio:.4f} red={red_ratio:.4f}")
    if red_ratio > min_ratio and red_ratio > gray_ratio:
        return "red"
    if gray_ratio > min_ratio and gray_ratio > red_ratio:
        return "gray"
    return None


def run_pulling_phase(sct: mss.mss, regions: dict, keybinds: dict, shared: SharedState,
                       dry_run: bool, timeout_seconds: float, end_confirm_seconds: float,
                       first_appear_timeout_seconds: float = 3.0) -> None:
    """Fase de puxar. Duas situacoes SAO DIFERENTES e precisam de logica
    diferente:

    1) O painel "Calmo"/"Puxando forte" ainda NAO apareceu nem uma vez desde
       o ESPACO (`panel_seen=False`) -- o jogo pode levar alguns frames pra
       desenhar o painel (variacao normal de renderizacao/rede). Aqui a
       gente da uma folga de `first_appear_timeout_seconds` antes de
       desistir, em vez de tratar como "peixe fugiu".
    2) O painel JA apareceu antes e agora nao esta mais classificando nada
       (`panel_seen=True`) -- aqui sim, depois do painel ficar ausente por
       `end_confirm_seconds` SEGUIDOS (tempo real, nao contagem de frames --
       ver nota abaixo), e porque o painel realmente sumiu (peixe
       capturado/perdido).

    Antes dessa distincao, um ciclo em que o painel demorasse so um pouco
    mais que ~0.3s pra aparecer era abortado achando que o peixe tinha
    fugido, sem nunca chegar a apertar puxar/dar linha.

    Por que tempo real (`end_confirm_seconds`) e nao contagem de frames:
    a confirmacao de "painel sumiu" costumava contar um NUMERO de leituras
    seguidas sem match (`end_confirm_frames`, ex: 15) antes de desistir. O
    problema e que o tempo real que isso leva depende de quao rapido cada
    iteracao do loop roda (captura de tela + processamento de cor), que
    varia de maquina pra maquina e ate de frame pra frame -- na pratica,
    15 frames podiam passar em bem menos de meio segundo, tempo curto
    demais pra distinguir "o painel realmente sumiu" de "essa leitura em
    especifico nao bateu com a cor configurada" (flicker de renderizacao,
    frame de transicao do jogo, etc.). Isso causava falso positivo: o bot
    via UMA leitura valida (ex: 'gray') e, logo em seguida, um punhado de
    leituras ruins, e ja declarava "peixe capturado" quase no mesmo
    instante do ESPACO -- antes da puxada de verdade ter sequer comecado.
    Contar segundos corridos em vez de frames torna a confirmacao imune a
    variacao de velocidade do loop, e o valor default (ver
    config_store.DEFAULTS) e alto o suficiente pra ignorar uma leitura
    ruim isolada, mas ainda curto o bastante pra nao atrasar perceptivelmente
    a deteccao de uma captura/fuga real."""
    debounce_needed = 2
    last_state = None
    stable_count = 0
    none_since: float | None = None
    panel_seen = False
    start = time.time()

    try:
        while time.time() - start < timeout_seconds:
            if shared.should_stop_cycle():
                return

            state = classify_pull_state(sct, regions)
            shared.update(fish_state_text={"gray": "Calmo", "red": "Puxando forte", None: "-"}[state])

            if state is not None:
                panel_seen = True
                none_since = None
            elif not panel_seen:
                if time.time() - start >= first_appear_timeout_seconds:
                    log.warning(
                        f"Painel de puxar nunca apareceu em {first_appear_timeout_seconds:.1f}s "
                        f"apos o ESPACO -- a regiao 'pulling_state' ou as cores em DEFAULT_COLORS "
                        f"provavelmente nao batem com este jogo/tela. Rode com --debug pra ver as "
                        f"proporcoes de cor e as screenshots da regiao capturada."
                    )
                    return
            else:
                if none_since is None:
                    none_since = time.time()
                elif time.time() - none_since >= end_confirm_seconds:
                    log.info(f"Painel de pesca sumiu (ausente por {end_confirm_seconds:.2f}s "
                             f"seguidos) -> peixe capturado/perdido")
                    return

            if state == last_state:
                stable_count += 1
            else:
                stable_count = 0
                last_state = state

            if stable_count >= debounce_needed and state is not None:
                target_key = keybinds["pull_key"] if state == "gray" else keybinds["release_key"]
                if stable_count == debounce_needed:
                    log.info(f"Estado='{state}' -> segurando '{target_key}'"
                             + (" (dry-run, nenhuma tecla enviada)" if dry_run else ""))
                if not dry_run:
                    input_sim.ensure_only(target_key)

            time.sleep(0.02)

        log.warning("Timeout na fase de puxar o peixe"
                     + ("" if panel_seen else " (painel nunca chegou a aparecer)"))
    finally:
        if not dry_run:
            input_sim.release_all()


def run_start_sequence(keybinds: dict, dry_run: bool, hwnd: int | None = None) -> None:
    # Simulacao de teclado (pydirectinput/SendInput) vai SEMPRE pra janela em
    # primeiro plano do sistema, nao pra uma janela especifica -- se o FiveM
    # nao estiver em foco nesse instante (usuario alt-tabou pro terminal do
    # bot, por exemplo), a tecla vai pra outro lugar e o jogo nunca recebe
    # nada, mesmo que o resto da automacao esteja funcionando certinho.
    if hwnd is not None and not dry_run and not window_detect.is_foreground(hwnd):
        if not window_detect.bring_to_foreground(hwnd):
            log.warning(
                "FiveM nao esta em primeiro plano e nao consegui trazer ele pra frente "
                "automaticamente (o Windows as vezes bloqueia isso) -- clique na janela "
                "do jogo AGORA, senao esta tecla nao vai chegar nele."
            )
    log.info(f"Pressionando '{keybinds['use_item_key']}' (iniciar pesca)")
    if not dry_run:
        input_sim.tap(keybinds["use_item_key"], hold_seconds=0.05)


def do_one_cast(sct: mss.mss, regions: dict, keybinds: dict, timings: dict,
                 shared: SharedState, dry_run: bool = False, hwnd: int | None = None) -> bool:
    """Executa um ciclo completo de pesca (lancar -> esperar fisgada ->
    timing -> puxar). Retorna True se completou (peixe capturado/perdido de
    forma 'normal'), False se abortou por timeout ou pedido de parada.
    Atualiza shared.state a cada fase. `hwnd`, quando fornecido, e usado pra
    garantir que o FiveM esta em primeiro plano antes de simular teclado
    (ver run_start_sequence)."""
    if shared.should_stop_cycle():
        return False

    run_start_sequence(keybinds, dry_run, hwnd)

    shared.set_state(AppState.AGUARDANDO_MINIGAME, "Aguardando a linha afundar e o peixe beliscar...")
    if not wait_for_bite(sct, regions, shared, dry_run, timings["bite_timeout_seconds"]):
        return False

    shared.set_state(AppState.AUTOMACAO, "Peixe beliscou! Esperando o momento certo pra fisgar...")
    if not run_timing_minigame(sct, regions, keybinds, shared, dry_run, timings["hit_timeout_seconds"]):
        return False

    shared.set_state(AppState.AUTOMACAO, "Puxando o peixe...")
    run_pulling_phase(sct, regions, keybinds, shared, dry_run,
                       timings["pulling_timeout_seconds"],
                       timings.get("end_confirm_seconds", 1.2),
                       timings.get("pull_panel_first_appear_timeout_seconds", 3.0))

    shared.update(casts_done=shared.casts_done + 1, fish_state_text="-", distance_text="-")
    shared.set_state(AppState.CAPTURA_CONCLUIDA)
    return True
