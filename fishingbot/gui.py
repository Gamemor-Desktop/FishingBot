"""
Interface grafica minimalista (Tkinter -- vem com o Python, nao precisa de
dependencia extra e empacota bem com o PyInstaller). So mostra estado e tem
os botoes Iniciar/Parar; toda a logica pesada roda na thread do Controller.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from .app_state import AppState, SharedState
from .controller import Controller

log = logging.getLogger("fishingbot")

REFRESH_MS = 250

STATE_COLORS = {
    AppState.INICIALIZANDO: "#888888",
    AppState.PROCURANDO_FIVEM: "#c9a227",
    AppState.DETECTANDO_JANELA: "#c9a227",
    AppState.CALIBRANDO: "#c9a227",
    AppState.AGUARDANDO_MINIGAME: "#2f7d32",
    AppState.AUTOMACAO: "#1565c0",
    AppState.CAPTURA_CONCLUIDA: "#1565c0",
    AppState.AGUARDANDO_CONFIRMACAO_MANUAL: "#e65100",
    AppState.PARADO: "#888888",
    AppState.ERRO: "#c62828",
}

# Cor de fundo usada pra destacar o status quando o app esta parado
# esperando a confirmacao manual (ENTER) -- precisa chamar bem mais
# atencao que os outros estados, ja que exige uma acao do jogador.
MANUAL_WAIT_BG = "#fff3cd"
MANUAL_WAIT_FG = "#7a4a00"


class FishingBotApp:
    def __init__(self, root: tk.Tk, dry_run: bool = False):
        self.root = root
        self.shared = SharedState()
        self.controller = Controller(self.shared, dry_run=dry_run)

        root.title("FishingBot")
        root.geometry("340x400")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_widgets()
        self.controller.start()
        self.root.after(REFRESH_MS, self._refresh)

    # -- construcao da interface -------------------------------------------

    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 4}

        header = tk.Label(self.root, text="FISHING BOT", font=("Segoe UI", 16, "bold"))
        header.pack(pady=(14, 8))

        info_frame = tk.Frame(self.root)
        info_frame.pack(fill="x", **pad)

        self.rows: dict[str, tuple[tk.Label, tk.Label]] = {}
        for key, label in [
            ("fivem", "FiveM:"),
            ("resolution", "Resolucao:"),
            ("dpi", "Escala:"),
            ("calibration", "Calibracao:"),
        ]:
            row = tk.Frame(info_frame)
            row.pack(fill="x", pady=2)
            name_lbl = tk.Label(row, text=label, width=12, anchor="w", font=("Segoe UI", 10))
            name_lbl.pack(side="left")
            value_lbl = tk.Label(row, text="-", anchor="w", font=("Segoe UI", 10, "bold"))
            value_lbl.pack(side="left")
            self.rows[key] = (name_lbl, value_lbl)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=8)

        self.status_label = tk.Label(self.root, text="Status: Inicializando...",
                                      font=("Segoe UI", 10), wraplength=310, justify="left")
        self.status_label.pack(fill="x", **pad)
        self._default_status_bg = self.status_label.cget("bg")

        self.detail_label = tk.Label(self.root, text="", font=("Segoe UI", 9), fg="#555555",
                                      wraplength=310, justify="left")
        self.detail_label.pack(fill="x", padx=10)

        self.casts_label = tk.Label(self.root, text="Peixes capturados: 0", font=("Segoe UI", 9))
        self.casts_label.pack(fill="x", padx=10, pady=(4, 0))

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=16)

        self.start_btn = tk.Button(btn_frame, text="INICIAR", width=14, bg="#2f7d32", fg="white",
                                    font=("Segoe UI", 10, "bold"), command=self._on_start)
        self.start_btn.grid(row=0, column=0, padx=6)

        self.stop_btn = tk.Button(btn_frame, text="PARAR", width=14, bg="#c62828", fg="white",
                                   font=("Segoe UI", 10, "bold"), command=self._on_stop)
        self.stop_btn.grid(row=0, column=1, padx=6)

        self.error_label = tk.Label(self.root, text="", font=("Segoe UI", 9), fg="#c62828",
                                     wraplength=310, justify="left")
        self.error_label.pack(fill="x", padx=10, pady=(6, 0))

        self._set_buttons_state(running=False)

    # -- acoes dos botoes -----------------------------------------------

    def _on_start(self) -> None:
        self.shared.update(user_wants_running=True)
        self._set_buttons_state(running=True)

    def _on_stop(self) -> None:
        self.shared.update(user_wants_running=False)
        self._set_buttons_state(running=False)

    def _on_close(self) -> None:
        self.controller.request_quit()
        self.root.after(150, self.root.destroy)

    def _set_buttons_state(self, running: bool) -> None:
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    # -- atualizacao periodica -------------------------------------------

    def _refresh(self) -> None:
        snap = self.shared.snapshot()

        fivem_lbl = self.rows["fivem"][1]
        fivem_lbl.config(text="Detectado" if snap["fivem_found"] else "Nao encontrado",
                          fg="#2f7d32" if snap["fivem_found"] else "#c62828")

        self.rows["resolution"][1].config(text=snap["resolution"])
        self.rows["dpi"][1].config(text=snap["dpi_scale"])

        calib_lbl = self.rows["calibration"][1]
        calib_lbl.config(text="Concluida" if snap["calibration_ok"] else "Pendente",
                          fg="#2f7d32" if snap["calibration_ok"] else "#888888")

        color = STATE_COLORS.get(snap["state"], "#333333")
        if snap["state"] == AppState.AGUARDANDO_CONFIRMACAO_MANUAL:
            # Destaque forte: essa e a unica etapa em que o bot esta parado
            # esperando uma acao manual do jogador (pegar/cortar o peixe e
            # apertar ENTER), entao precisa ser bem visivel na interface.
            self.status_label.config(text=f"Status: {snap['status_message']}",
                                      fg=MANUAL_WAIT_FG, bg=MANUAL_WAIT_BG,
                                      font=("Segoe UI", 10, "bold"))
        else:
            self.status_label.config(text=f"Status: {snap['status_message']}", fg=color,
                                      bg=self._default_status_bg, font=("Segoe UI", 10))

        detail_bits = []
        if snap["fish_state_text"] not in ("-", ""):
            detail_bits.append(f"Peixe: {snap['fish_state_text']}")
        if snap["distance_text"] not in ("-", ""):
            detail_bits.append(f"Distancia: {snap['distance_text']}")
        self.detail_label.config(text="   ".join(detail_bits))

        self.casts_label.config(text=f"Peixes capturados: {snap['casts_done']}")

        self.error_label.config(text=snap["error_message"])

        # mantem os botoes coerentes mesmo se o estado mudar por outro
        # motivo (ex: FiveM fechou e o controller nao alterou user_wants_running)
        self._set_buttons_state(running=snap["user_wants_running"])

        if not snap["quit_requested"]:
            self.root.after(REFRESH_MS, self._refresh)


def run_app(dry_run: bool = False) -> None:
    root = tk.Tk()
    FishingBotApp(root, dry_run=dry_run)
    root.mainloop()
