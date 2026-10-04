"""
Estado compartilhado entre a thread do controlador (deteccao/calibracao/
automacao) e a thread da interface grafica (Tkinter). Tudo protegido por um
lock simples -- o volume de leituras/escritas e baixo (poucas vezes por
segundo), entao um Lock comum e suficiente, sem necessidade de filas.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto


class AppState(Enum):
    INICIALIZANDO = auto()
    PROCURANDO_FIVEM = auto()
    DETECTANDO_JANELA = auto()
    CALIBRANDO = auto()
    AGUARDANDO_MINIGAME = auto()
    AUTOMACAO = auto()
    CAPTURA_CONCLUIDA = auto()
    AGUARDANDO_CONFIRMACAO_MANUAL = auto()
    PARADO = auto()
    ERRO = auto()


STATE_LABELS = {
    AppState.INICIALIZANDO: "Inicializando...",
    AppState.PROCURANDO_FIVEM: "Procurando FiveM...",
    AppState.DETECTANDO_JANELA: "Detectando janela/area do jogo...",
    AppState.CALIBRANDO: "Calibrando regioes de reconhecimento...",
    AppState.AGUARDANDO_MINIGAME: "Aguardando pesca...",
    AppState.AUTOMACAO: "Automacao em andamento (minigame ativo)",
    AppState.CAPTURA_CONCLUIDA: "Peixe capturado!",
    # Etapa manual (nao automatizada por enquanto): o bot NAO inicia uma
    # nova pescaria sozinho aqui -- fica parado ate o jogador apertar ENTER,
    # depois de pegar e cortar o peixe manualmente no jogo.
    AppState.AGUARDANDO_CONFIRMACAO_MANUAL: (
        "Peixe capturado!\n"
        "Pegue e corte o peixe manualmente.\n"
        "Pressione ENTER quando estiver pronto para pescar novamente."
    ),
    AppState.PARADO: "Parado",
    AppState.ERRO: "Erro",
}


# Texto curto do status em ERRO; o detalhe fica em error_message (rotulo
# vermelho da interface), pra nao aparecer duas vezes na tela.
ERRO_STATUS_TEXT = "Parado por seguranca."


@dataclass
class SharedState:
    _lock: threading.Lock = field(default_factory=threading.Lock)

    state: AppState = AppState.INICIALIZANDO
    status_message: str = "Inicializando..."

    fivem_found: bool = False
    window_title: str = ""
    resolution: str = "-"
    dpi_scale: str = "-"
    calibration_ok: bool = False
    last_calibrated_at: float = 0.0

    user_wants_running: bool = False  # controlado pelos botoes Iniciar/Parar
    quit_requested: bool = False      # fechar o app / panic

    casts_done: int = 0
    fish_state_text: str = "-"        # 'Calmo' / 'Puxando forte' / '-'

    error_message: str = ""

    # Motivo pelo qual o ciclo de pesca em andamento deve ser abortado (janela
    # sumiu/mudou, detectado pelo watchdog do controlador). Vazio = nenhum.
    # Qualquer fase checa isso via should_stop_cycle(), sem mudar assinaturas.
    abort_reason: str = ""

    # Motivo da PAUSA do ciclo (FiveM minimizado / sem foco). Diferente de
    # abort_reason: pausar NAO cancela o lance -- as fases congelam (sem
    # teclas, sem gastar timeout) e seguem de onde pararam quando o jogo volta.
    pause_reason: str = ""

    config_notice: str = ""       # aviso de valores invalidos corrigidos no config.json
    stats_text: str = ""          # resumo da sessao (lances, capturas, falhas seguidas)
    # time.monotonic() do ultimo "progresso" (inicio da automacao, captura,
    # retomada pelo ENTER). O monitor de saude para o bot se isto ficar velho.
    last_progress_at: float = 0.0

    def set_state(self, new_state: AppState, message: str | None = None) -> None:
        with self._lock:
            self.state = new_state
            self.status_message = message or STATE_LABELS.get(new_state, new_state.name)

    def update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "status_message": self.status_message,
                "fivem_found": self.fivem_found,
                "window_title": self.window_title,
                "resolution": self.resolution,
                "dpi_scale": self.dpi_scale,
                "calibration_ok": self.calibration_ok,
                "last_calibrated_at": self.last_calibrated_at,
                "user_wants_running": self.user_wants_running,
                "quit_requested": self.quit_requested,
                "casts_done": self.casts_done,
                "fish_state_text": self.fish_state_text,
                "error_message": self.error_message,
                "abort_reason": self.abort_reason,
                "pause_reason": self.pause_reason,
                "stats_text": self.stats_text,
                "config_notice": self.config_notice,
                "last_progress_at": self.last_progress_at,
            }

    def should_stop_cycle(self) -> bool:
        """True se a automacao do ciclo atual deve abortar (usuario apertou
        Parar, o app esta sendo fechado, ou o watchdog pediu aborto)."""
        with self._lock:
            return (self.quit_requested or not self.user_wants_running
                    or bool(self.abort_reason))

    def request_abort(self, reason: str) -> None:
        """Pede pra abortar o ciclo atual (o primeiro motivo registrado vale)."""
        with self._lock:
            if not self.abort_reason:
                self.abort_reason = reason

    def set_pause(self, reason: str) -> None:
        with self._lock:
            self.pause_reason = reason

    def clear_pause(self) -> None:
        with self._lock:
            self.pause_reason = ""

    def checkpoint(self) -> float:
        """Chamado pelas fases no topo de cada iteracao. Enquanto o ciclo
        estiver pausado, bloqueia ate voltar (ou mandarem parar/abortar) e
        devolve quantos segundos ficou parado, pra fase empurrar seus
        timeouts -- o tempo em que o jogo estava minimizado nao conta."""
        t0 = None
        while True:
            with self._lock:
                paused = bool(self.pause_reason) and not (
                    self.quit_requested or not self.user_wants_running or self.abort_reason)
            if not paused:
                break
            if t0 is None:
                t0 = time.monotonic()
            time.sleep(0.05)
        return 0.0 if t0 is None else time.monotonic() - t0

    def mark_progress(self) -> None:
        with self._lock:
            self.last_progress_at = time.monotonic()

    def clear_abort(self) -> None:
        with self._lock:
            self.abort_reason = ""

    def fail(self, message: str) -> None:
        """Parada de seguranca: para o bot, mostra o erro na interface e
        mantem o estado ERRO ate o usuario apertar INICIAR de novo."""
        with self._lock:
            self.user_wants_running = False
            self.error_message = message
            self.state = AppState.ERRO
            self.status_message = ERRO_STATUS_TEXT
