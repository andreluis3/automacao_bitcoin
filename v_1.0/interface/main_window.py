from __future__ import annotations

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from interface.bot_controller import BotController
from interface.janela_simulacao import JanelaSimulacao
from interface.ui_bridge import UIBridge


ctk.set_appearance_mode("dark")


class TradingApp(ctk.CTk):
    def __init__(self, market_data):
        super().__init__()
        self.title("Automação Bitcoin")
        self.geometry("1280x820")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = BotController(market_data=market_data, log_callback=self._enqueue_log)
        self.bridge = UIBridge(self)
        self._pending_logs: list[str] = []

        self.max_candles = 180
        self.prices: list[float] = []

        self._criar_layout()
        self._criar_grafico()
        self._aplicar_config_inicial_ui()
        self._flush_pending_logs()
        self._atualizar_lock_real()

        self.after(400, self.loop_principal)

    def _criar_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=14)
        header.pack(fill="x", padx=18, pady=(14, 6))

        self.preco_label = ctk.CTkLabel(
            header,
            text=(
                "BTC/USDT: --  Modo: SIMULACAO  Saldo R$: 0.00  "
                "Saldo BTC: 0.00000000  Taxas: 0.00  Drawdown Atual: 0.00%"
            ),
            font=("Arial", 18, "bold"),
        )
        self.preco_label.pack(side="left", padx=16, pady=12)

        body = ctk.CTkFrame(self, fg_color="#1e1f22")
        body.pack(fill="both", expand=True, padx=18, pady=8)
        body.grid_columnconfigure(0, weight=5)
        body.grid_columnconfigure(1, weight=0, minsize=340)
        body.grid_rowconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=0)

        self.chart_frame = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=14)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        side = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=14, width=340)
        side.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="CONTROLE DO BOT", font=("Arial", 17, "bold")).pack(pady=(16, 8))

        status_row = ctk.CTkFrame(side, fg_color="transparent")
        status_row.pack(fill="x", padx=16, pady=(2, 8))
        self.led_status = ctk.CTkLabel(status_row, text="●", font=("Arial", 26), text_color="#6b7280")
        self.led_status.pack(side="left")
        self.badge_status = ctk.CTkLabel(status_row, text="PARADO", font=("Arial", 13, "bold"))
        self.badge_status.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(side, text="Modo", anchor="w").pack(fill="x", padx=16)
        self.mode_switch = ctk.CTkSegmentedButton(
            side,
            values=["SIMULACAO", "REAL"],
            command=self._on_mode_change,
        )
        self.mode_switch.pack(fill="x", padx=16, pady=(6, 6))
        self.lock_label = ctk.CTkLabel(side, text="", text_color="#f59e0b", font=("Arial", 12, "bold"))
        self.lock_label.pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkLabel(side, text="Perfil", anchor="w").pack(fill="x", padx=16)
        self.profile_combo = ctk.CTkComboBox(
            side,
            values=["Conservador", "Agressivo"],
            state="readonly",
            command=self._on_profile_change,
        )
        self.profile_combo.pack(fill="x", padx=16, pady=(6, 12))

        self.start_button = ctk.CTkButton(
            side,
            text="INICIAR",
            height=42,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._on_start_clicked,
        )
        self.start_button.pack(fill="x", padx=16, pady=(4, 8))

        self.stop_button = ctk.CTkButton(
            side,
            text="PARAR",
            height=42,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._on_stop_clicked,
        )
        self.stop_button.pack(fill="x", padx=16, pady=(0, 10))

        self.config_button = ctk.CTkButton(
            side,
            text="⚙ Configurações",
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            command=self._abrir_janela_simulacao,
        )
        self.config_button.pack(fill="x", padx=16, pady=(0, 14))

        cards = ctk.CTkFrame(side, fg_color="#1f2937", corner_radius=12)
        cards.pack(fill="x", padx=16, pady=(2, 12))

        self.card_lucro_value = self._create_card(cards, "Lucro Hoje", "R$ 0.00")
        self.card_saldo_value = self._create_card(cards, "Saldo Atual", "R$ 0.00")
        self.card_drawdown_value = self._create_card(cards, "Drawdown", "0.00%")

        self.drawdown_progress = ctk.CTkProgressBar(cards, progress_color="#ef4444")
        self.drawdown_progress.set(0)
        self.drawdown_progress.pack(fill="x", padx=12, pady=(2, 12))

        console_frame = ctk.CTkFrame(body, fg_color="#111827", corner_radius=12)
        console_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        ctk.CTkLabel(console_frame, text="Console de Logs", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

        self.console_box = ctk.CTkTextbox(console_frame, height=170, state="disabled")
        self.console_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def _create_card(self, parent, title: str, value: str):
        card = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=10)
        card.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(card, text=title, text_color="#9ca3af", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(8, 2))
        value_label = ctk.CTkLabel(card, text=value, font=("Arial", 18, "bold"))
        value_label.pack(anchor="w", padx=10, pady=(0, 8))
        return value_label

    def _criar_grafico(self) -> None:
        self.fig, self.ax = plt.subplots(figsize=(8, 5))
        self.fig.patch.set_facecolor("#2a2d31")
        self.ax.set_facecolor("#1e1f22")

        self.price_line, = self.ax.plot([], [], color="#e5e7eb", linewidth=1.6)
        self.ma_fast_line, = self.ax.plot([], [], color="#22c55e", linewidth=1.0)
        self.ma_slow_line, = self.ax.plot([], [], color="#ef4444", linewidth=1.0)
        self.ax.tick_params(colors="#e5e7eb")
        self.ax.grid(color="#374151", alpha=0.5)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _redesenhar_grafico(self, preco: float) -> None:
        if preco <= 0:
            return
        self.prices.append(float(preco))
        if len(self.prices) > self.max_candles:
            self.prices = self.prices[-self.max_candles :]

        x = np.arange(len(self.prices))
        y = np.array(self.prices)

        self.price_line.set_data(x, y)

        if len(y) >= 9:
            ma_fast = np.convolve(y, np.ones(9) / 9, mode="valid")
            self.ma_fast_line.set_data(x[-len(ma_fast) :], ma_fast)
        else:
            self.ma_fast_line.set_data([], [])

        if len(y) >= 21:
            ma_slow = np.convolve(y, np.ones(21) / 21, mode="valid")
            self.ma_slow_line.set_data(x[-len(ma_slow) :], ma_slow)
        else:
            self.ma_slow_line.set_data([], [])

        if len(self.prices) > 1:
            self.ax.set_xlim(0, len(self.prices) - 1)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def loop_principal(self) -> None:
        snapshot = self.controller.get_runtime_snapshot()
        self._redesenhar_grafico(float(snapshot.get("price_usdt", 0.0)))
        self.bridge.update_dashboard(snapshot)
        self.after(1000, self.loop_principal)

    def _on_start_clicked(self) -> None:
        ok, msg = self.controller.start_bot()
        self.bridge.log_message(msg)
        self._atualizar_botoes_por_estado()

    def _on_stop_clicked(self) -> None:
        ok, msg = self.controller.stop_bot()
        self.bridge.log_message(msg)
        self._atualizar_botoes_por_estado()

    def _on_mode_change(self, value: str) -> None:
        mode = "real" if str(value).upper() == "REAL" else "simulacao"
        self.controller.set_mode(mode)
        self._atualizar_lock_real()
        self._atualizar_botoes_por_estado()

    def _on_profile_change(self, profile: str) -> None:
        self.controller.apply_profile(profile)

    def _abrir_janela_simulacao(self) -> None:
        if hasattr(self, "_cfg_window") and self._cfg_window is not None and self._cfg_window.winfo_exists():
            self._cfg_window.focus()
            return
        self._cfg_window = JanelaSimulacao(
            self,
            config=self.controller.config,
            on_save=self._salvar_config_popup,
            on_start=self._on_start_clicked,
        )

    def _salvar_config_popup(self, data: dict) -> None:
        self.controller.update_config(data)
        perfil = str(data.get("perfil", "Conservador"))
        self.profile_combo.set(perfil)
        self.bridge.log_message("Configuração atualizada pelo popup.")

    def _aplicar_config_inicial_ui(self) -> None:
        perfil = str(self.controller.config.get("perfil", "Conservador"))
        self.profile_combo.set(perfil)

        modo = str(self.controller.config.get("modo", "simulacao"))
        self.mode_switch.set("REAL" if modo == "real" else "SIMULACAO")

        self._atualizar_botoes_por_estado()
        self.bridge.log_message("Config carregada de config.json")

    def _atualizar_lock_real(self) -> None:
        if not self.controller.real_api_available:
            self.lock_label.configure(text="REAL LOCKED: sem API válida")
        else:
            self.lock_label.configure(text="")

    def _atualizar_botoes_por_estado(self) -> None:
        running = self.controller.bot_state in {"simulando", "real"}
        if running:
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        else:
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

        if self.controller.config.get("modo") == "real" and not self.controller.real_api_available:
            self.start_button.configure(state="disabled")

    def _enqueue_log(self, msg: str) -> None:
        if hasattr(self, "console_box"):
            self.bridge.log_message(msg)
        else:
            self._pending_logs.append(msg)

    def _flush_pending_logs(self) -> None:
        for msg in self._pending_logs:
            self.bridge.log_message(msg)
        self._pending_logs.clear()

    def _on_close(self) -> None:
        self.controller.shutdown()
        self.destroy()


class MainWindow(TradingApp):
    pass
