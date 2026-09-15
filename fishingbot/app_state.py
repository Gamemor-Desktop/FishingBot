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
    distance_text: str = "-"

    error_message: str = ""

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
                "distance_text": self.distance_text,
                "error_message": self.error_message,
            }

    def should_stop_cycle(self) -> bool:
        """True se a automacao do ciclo atual deve abortar (usuario apertou
        Parar, ou o app esta sendo fechado)."""
        with self._lock:
            return self.quit_requested or not self.user_wants_running
