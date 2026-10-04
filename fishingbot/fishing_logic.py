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

from . import debug_tools, input_sim, vision
from .app_state import AppState, SharedState
from .regions import DEFAULT_COLORS, Region
from .stats import CastOutcome

log = logging.getLogger("fishingbot")


def _read_hook(sct: mss.mss, roi: Region) -> vision.HookReading:
    frame = vision.grab(sct, roi.as_roi())
    reading = vision.read_hook(frame, DEFAULT_COLORS["hook_zone"])
    debug_tools.save_roi("hook_zone", frame, reading.mask)
    return reading


NO_BITE_YET_MESSAGE = (
    "Ainda sem mordida. Se a pesca nem comecou (vara nao equipada, menu ou "
    "inventario aberto, longe do local de pesca), pare o bot e posicione o personagem."
)


def wait_for_bite(sct: mss.mss, regions: dict, shared: SharedState, dry_run: bool,
                   timeout_seconds: float, cast_check_seconds: float) -> bool:
    """Espera a bolinha da mordida aparecer (forma de disco brilhante, ver
    vision.read_hook), em 2 frames seguidos.

    Se passar `cast_check_seconds` sem o aviso 'Parar de pescar' nem mordida,
    avisa na interface (so informa, nao cancela o lance). ATENCAO: no jogo esse
    aviso aparece junto da mordida (~1s antes da bolinha, ~16s depois do lance
    num teste real), NAO logo depois de lancar -- por isso o prazo e longo: um
    prazo curto dispararia em toda pescaria normal."""
    hz = regions["hook_zone"]
    start = time.monotonic()
    confirm = 0
    prompt_seen = False
    warned = False
    next_prompt_check = 0.0
    stop_cfg = DEFAULT_COLORS["stop_prompt"]
    while time.monotonic() - start < timeout_seconds:
        if shared.should_stop_cycle():
            return False
        paused = shared.checkpoint()  # jogo minimizado/sem foco: congela
        if paused:
            start += paused
            confirm = 0
            continue
        now = time.monotonic()
        if not prompt_seen and now >= next_prompt_check and "pulling_state" in regions:
            next_prompt_check = now + 0.25
            roi = regions["pulling_state"]
            if vision.stop_prompt_visible(vision.grab(sct, roi.as_roi()), stop_cfg):
                prompt_seen = True
                if warned:
                    warned = False
                    shared.set_state(AppState.AGUARDANDO_MINIGAME,
                                      "Aguardando a linha afundar e o peixe beliscar...")
        if not prompt_seen and not warned and now - start >= cast_check_seconds:
            warned = True
            log.warning(NO_BITE_YET_MESSAGE)
            shared.set_state(AppState.AGUARDANDO_MINIGAME, NO_BITE_YET_MESSAGE)
        reading = _read_hook(sct, hz)
        debug_tools.log_ratio("hook_zone_bite", reading.bright_ratio, None,
                               extra=f"bolinha={'SIM' if reading.ball else 'nao'} "
                                     f"aviso_parar_de_pescar={'SIM' if prompt_seen else 'nao'}")
        if reading.ball:
            confirm += 1
            if confirm >= 2:
                return True
        else:
            confirm = 0
        time.sleep(0.02)
    return False


def run_timing_minigame(sct: mss.mss, regions: dict, keybinds: dict, shared: SharedState,
                         dry_run: bool, timeout_seconds: float) -> bool:
    """Espera o peixe vermelho alinhar (proporcao de pixels brilhantes acima de
    hit_min_ratio por `hit_confirm_frames` frames seguidos) e aperta ESPACO."""
    hz = regions["hook_zone"]
    colors = DEFAULT_COLORS["hook_zone"]
    needed = max(1, int(colors["hit_confirm_frames"]))
    start = time.monotonic()
    streak = 0
    while time.monotonic() - start < timeout_seconds:
        if shared.should_stop_cycle():
            return False
        paused = shared.checkpoint()
        if paused:
            start += paused
            streak = 0
            continue
        reading = _read_hook(sct, hz)
        debug_tools.log_ratio("hook_zone_hit", reading.bright_ratio, colors["hit_min_ratio"])
        streak = streak + 1 if reading.bright_ratio >= colors["hit_min_ratio"] else 0
        if streak >= needed:
            log.info(f"Peixe alinhado (ratio={reading.bright_ratio:.4f}) -> ESPACO")
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
    red_mask = vision.hsv_mask_multi(frame, red["ranges"])
    gray_ratio = vision.pixel_ratio(gray_mask)
    red_ratio = vision.pixel_ratio(red_mask)
    text_cfg = DEFAULT_COLORS["pulling_text"]
    text_ratio, near_dark = vision.panel_text_features(frame, text_cfg)
    min_ratio = 0.3
    debug_tools.save_roi("pulling_state", frame)
    debug_tools.log_ratio("pulling_state", max(gray_ratio, red_ratio), min_ratio,
                           extra=f"gray={gray_ratio:.4f} red={red_ratio:.4f} "
                                 f"texto={text_ratio:.4f} fundo_escuro={near_dark:.2f}")
    # Sem o texto branco do painel nao ha painel, por mais que a cor "bata"
    # (ex: aviso 'Parar de pescar' sobre agua escura, madeira marrom).
    if text_ratio < text_cfg["min_ratio"]:
        return None
    if red_ratio > min_ratio and red_ratio > gray_ratio:
        return "red"
    if gray_ratio > min_ratio and gray_ratio > red_ratio:
        return "gray"
    # A caixa e translucida: sobre fundo marrom/claro a cor nao bate, mas o
    # texto branco sobre fundo escuro, sem nada vermelho, e o "Calmo".
    if (text_cfg["calm_min_ratio"] <= text_ratio <= text_cfg["calm_max_ratio"]
            and near_dark >= text_cfg["calm_min_near_dark"]
            and red_ratio < text_cfg["calm_max_red_ratio"]):
        return "gray"
    return None


def run_pulling_phase(sct: mss.mss, regions: dict, keybinds: dict, shared: SharedState,
                       dry_run: bool, timeout_seconds: float, end_confirm_seconds: float,
                       first_appear_timeout_seconds: float,
                       min_pull_seconds: float) -> CastOutcome:
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
    start = time.monotonic()

    try:
        while time.monotonic() - start < timeout_seconds:
            if shared.should_stop_cycle():
                return CastOutcome.STOPPED
            paused = shared.checkpoint()
            if paused:
                # o controlador soltou as teclas ao pausar; ao voltar, o painel
                # precisa ser relido do zero (nao conta como "sumiu")
                start += paused
                none_since = None
                stable_count = 0
                last_state = None
                continue

            state = classify_pull_state(sct, regions)
            shared.update(fish_state_text={"gray": "Calmo", "red": "Puxando forte", None: "-"}[state])

            if state == last_state:
                stable_count += 1
            else:
                stable_count = 0
                last_state = state
            confirmed = stable_count >= debounce_needed

            if state is not None:
                panel_seen = True
                # So cancela a contagem de "painel sumiu" com uma leitura
                # CONFIRMADA (debounced) do painel de volta. Um unico frame
                # de flicker (ex: animacao de fade-out do painel batendo por
                # coincidencia com a cor configurada por 1 frame isolado)
                # nao deve reiniciar o relogio -- isso era o que deixava a
                # tecla (W/S) presa bem alem da hora depois do peixe ja ter
                # saido da agua, porque cada flicker reiniciava o
                # end_confirm_seconds do zero.
                if confirmed:
                    none_since = None
            elif not panel_seen:
                if time.monotonic() - start >= first_appear_timeout_seconds:
                    log.warning(
                        f"Painel de puxar nunca apareceu em {first_appear_timeout_seconds:.1f}s "
                        f"apos o ESPACO -- a regiao 'pulling_state' ou as cores em DEFAULT_COLORS "
                        f"provavelmente nao batem com este jogo/tela. Rode com --debug pra ver as "
                        f"proporcoes de cor e as screenshots da regiao capturada."
                    )
                    return CastOutcome.NO_PANEL
            else:
                if none_since is None:
                    none_since = time.monotonic()
                elif (time.monotonic() - none_since >= end_confirm_seconds
                      and time.monotonic() - start >= min_pull_seconds):
                    log.info(f"Painel de pesca sumiu (ausente por {end_confirm_seconds:.2f}s "
                             f"seguidos) -> peixe capturado/perdido")
                    return CastOutcome.CAPTURED

            if confirmed and state is not None:
                target_key = keybinds["pull_key"] if state == "gray" else keybinds["release_key"]
                if stable_count == debounce_needed:
                    log.info(f"Estado='{state}' -> segurando '{target_key}'"
                             + (" (dry-run, nenhuma tecla enviada)" if dry_run else ""))
                if not dry_run:
                    input_sim.ensure_only(target_key)

            time.sleep(0.02)

        log.warning("Timeout na fase de puxar o peixe"
                     + ("" if panel_seen else " (painel nunca chegou a aparecer)"))
        return CastOutcome.PULL_TIMEOUT if panel_seen else CastOutcome.NO_PANEL
    finally:
        if not dry_run:
            input_sim.release_all()


def run_start_sequence(keybinds: dict, dry_run: bool, hwnd: int | None = None) -> None:
    # Simulacao de teclado (pydirectinput/SendInput) vai SEMPRE pra janela em
    # primeiro plano do sistema, nao pra uma janela especifica -- se o FiveM
    # nao estiver em foco nesse instante (usuario alt-tabou pro terminal do
    # bot, por exemplo), a tecla vai pra outro lugar e o jogo nunca recebe
    # nada, mesmo que o resto da automacao esteja funcionando certinho.
    # Nao puxamos o jogo pra frente aqui: se o usuario saiu do FiveM, o ciclo
    # esta PAUSADO (shared.checkpoint) e nenhuma tecla chega; e se o foco sumir
    # mesmo assim, a guarda de foco (input_sim) bloqueia a tecla.
    log.info(f"Pressionando '{keybinds['use_item_key']}' (iniciar pesca)")
    if not dry_run:
        input_sim.tap(keybinds["use_item_key"], hold_seconds=0.05)


def do_one_cast(sct: mss.mss, regions: dict, keybinds: dict, timings: dict,
                 shared: SharedState, dry_run: bool = False, hwnd: int | None = None) -> CastOutcome:
    """Executa um ciclo completo de pesca (lancar -> esperar fisgada ->
    timing -> puxar) e devolve COMO terminou (CastOutcome): CAPTURED, ou o
    motivo da falha, ou STOPPED se foi interrompido (parar/panico/watchdog --
    isso nao e falha). Atualiza shared.state a cada fase. `hwnd`, quando
    fornecido, e usado pra garantir que o FiveM esta em primeiro plano antes
    de simular teclado (ver run_start_sequence)."""
    def failed(outcome: CastOutcome) -> CastOutcome:
        return CastOutcome.STOPPED if shared.should_stop_cycle() else outcome

    if shared.should_stop_cycle():
        return CastOutcome.STOPPED

    shared.checkpoint()  # nao lanca a vara com o jogo minimizado/sem foco
    if shared.should_stop_cycle():
        return CastOutcome.STOPPED

    run_start_sequence(keybinds, dry_run, hwnd)

    shared.set_state(AppState.AGUARDANDO_MINIGAME, "Aguardando a linha afundar e o peixe beliscar...")
    if not wait_for_bite(sct, regions, shared, dry_run, timings["bite_timeout_seconds"],
                         timings["cast_confirm_seconds"]):
        return failed(CastOutcome.NO_BITE)

    shared.set_state(AppState.AUTOMACAO, "Peixe beliscou! Esperando o momento certo pra fisgar...")
    if not run_timing_minigame(sct, regions, keybinds, shared, dry_run, timings["hit_timeout_seconds"]):
        return failed(CastOutcome.HIT_TIMEOUT)

    shared.set_state(AppState.AUTOMACAO, "Puxando o peixe...")
    outcome = run_pulling_phase(sct, regions, keybinds, shared, dry_run,
                                 timings["pulling_timeout_seconds"],
                                 timings["end_confirm_seconds"],
                                 timings["pull_panel_first_appear_timeout_seconds"],
                                 timings["pull_min_seconds"])
    if outcome is not CastOutcome.CAPTURED:
        return failed(outcome)

    shared.update(casts_done=shared.casts_done + 1, fish_state_text="-", distance_text="-")
    shared.set_state(AppState.CAPTURA_CONCLUIDA)
    return CastOutcome.CAPTURED
