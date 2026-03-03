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
        self.geometry("1360x900")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = BotController(market_data=market_data, log_callback=self._enqueue_log)
        self.bridge = UIBridge(self)
        self._pending_logs: list[str] = []

        self.max_candles = 240
        self.prices: list[float] = []

        self._criar_layout()
        self._criar_grafico_trading()
        self._criar_graficos_performance()
        self._aplicar_config_inicial_ui()
        self._flush_pending_logs()
        self._atualizar_lock_real()
        self.after(400, self.loop_principal)

    def _criar_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="#1f232a", corner_radius=14)
        header.pack(fill="x", padx=18, pady=(14, 8))
        self.preco_label = ctk.CTkLabel(
            header,
            text="BTC/USDT: --",
            font=("Arial", 18, "bold"),
        )
        self.preco_label.pack(side="left", padx=16, pady=12)

        self.tabs = ctk.CTkTabview(self, fg_color="#161a20")
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.tab_trading = self.tabs.add("Trading")
        self.tab_performance = self.tabs.add("Performance")

        self._criar_tab_trading()
        self._criar_tab_performance()

    def _criar_tab_trading(self) -> None:
        body = ctk.CTkFrame(self.tab_trading, fg_color="#161a20")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=8)
        body.grid_columnconfigure(1, weight=2, minsize=340)
        body.grid_rowconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=0)

        self.chart_frame = ctk.CTkFrame(body, fg_color="#1f232a", corner_radius=14)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        side = ctk.CTkFrame(body, fg_color="#1f232a", corner_radius=14, width=340)
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
        self.mode_switch = ctk.CTkSegmentedButton(side, values=["SIMULACAO", "REAL"], command=self._on_mode_change)
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

        self.start_button = ctk.CTkButton(side, text="INICIAR", height=42, fg_color="#16a34a", hover_color="#15803d", command=self._on_start_clicked)
        self.start_button.pack(fill="x", padx=16, pady=(4, 8))
        self.stop_button = ctk.CTkButton(side, text="PARAR", height=42, fg_color="#dc2626", hover_color="#b91c1c", command=self._on_stop_clicked)
        self.stop_button.pack(fill="x", padx=16, pady=(0, 10))
        self.config_button = ctk.CTkButton(side, text="⚙ Configurações", height=36, fg_color="#334155", hover_color="#475569", command=self._abrir_janela_simulacao)
        self.config_button.pack(fill="x", padx=16, pady=(0, 14))

        self.accumulate_switch = ctk.CTkSwitch(side, text="Ativar Acumulação", command=self._on_accumulation_toggle)
        self.accumulate_switch.pack(anchor="w", padx=16, pady=(0, 10))

        cards = ctk.CTkFrame(side, fg_color="#0f172a", corner_radius=12)
        cards.pack(fill="x", padx=16, pady=(2, 12))
        self.card_lucro_value = self._create_card(cards, "Lucro Hoje", "R$ 0.00")
        self.card_equity_value = self._create_card(cards, "Equity Atual", "R$ 0.00")
        self.card_reserva_value = self._create_card(cards, "Reserva Segura", "R$ 0.00")
        self.card_exposicao_value = self._create_card(cards, "Exposição Atual", "R$ 0.00 (0.00%)")
        self.card_profit_factor_value = self._create_card(cards, "Profit Factor", "0.00")
        self.card_patrimonio_protegido_value = self._create_card(cards, "Patrimônio Protegido", "R$ 0.00")
        self.card_drawdown_value = self._create_card(cards, "Drawdown", "0.00%")
        self.card_alerta_value = ctk.CTkLabel(cards, text="", text_color="#f59e0b", font=("Arial", 12, "bold"))
        self.card_alerta_value.pack(anchor="w", padx=12, pady=(4, 8))
        self.drawdown_progress = ctk.CTkProgressBar(cards, progress_color="#ef4444")
        self.drawdown_progress.set(0)
        self.drawdown_progress.pack(fill="x", padx=12, pady=(2, 12))

        console_frame = ctk.CTkFrame(body, fg_color="#0b1220", corner_radius=12)
        console_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        ctk.CTkLabel(console_frame, text="Console de Logs", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        self.console_box = ctk.CTkTextbox(console_frame, height=170, state="disabled")
        self.console_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def _criar_tab_performance(self) -> None:
        root = ctk.CTkFrame(self.tab_performance, fg_color="#161a20")
        root.pack(fill="both", expand=True, padx=8, pady=8)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=1)

        zone1 = ctk.CTkFrame(root, fg_color="#1f232a", corner_radius=12)
        zone1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        zone1.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.perf_win_rate = self._create_big_card(zone1, 0, "Win Rate", "0.00%")
        self.perf_pf = self._create_big_card(zone1, 1, "Profit Factor", "0.00")
        self.perf_expect = self._create_big_card(zone1, 2, "Expectativa Matemática", "R$ 0.00")
        self.perf_dd = self._create_big_card(zone1, 3, "Drawdown Atual", "0.00%")
        self.perf_risk = self._create_big_card(zone1, 4, "Status de Risco", "VERDE")
        self.expectancy_text = ctk.CTkLabel(zone1, text="Para cada R$ 1 arriscado, retorno esperado: R$ 0.00", anchor="w")
        self.expectancy_text.grid(row=1, column=0, columnspan=5, sticky="ew", padx=12, pady=(2, 8))

        zone2 = ctk.CTkFrame(root, fg_color="#1f232a", corner_radius=12)
        zone2.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.perf_chart_frame = ctk.CTkFrame(zone2, fg_color="#1f232a")
        self.perf_chart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        zone3 = ctk.CTkFrame(root, fg_color="#1f232a", corner_radius=12)
        zone3.grid(row=2, column=0, sticky="nsew")
        zone3.grid_columnconfigure(0, weight=2)
        zone3.grid_columnconfigure(1, weight=1)
        zone3.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(zone3, text="Deep Logs", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        ctk.CTkLabel(zone3, text="Quase-Trades", font=("Arial", 14, "bold")).grid(row=0, column=1, sticky="w", padx=10, pady=(8, 4))

        self.deep_logs_box = ctk.CTkTextbox(zone3, state="disabled")
        self.deep_logs_box.grid(row=1, column=0, sticky="nsew", padx=(10, 6), pady=(0, 10))
        self.near_trades_box = ctk.CTkTextbox(zone3, state="disabled")
        self.near_trades_box.grid(row=1, column=1, sticky="nsew", padx=(6, 10), pady=(0, 10))

        self.confluence_panel = ctk.CTkFrame(zone3, fg_color="#0f172a", corner_radius=10)
        self.confluence_panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        self.confluence_rsi = ctk.CTkLabel(self.confluence_panel, text="RSI: 🔴")
        self.confluence_dist = ctk.CTkLabel(self.confluence_panel, text="Distância SMA: 🔴")
        self.confluence_vol = ctk.CTkLabel(self.confluence_panel, text="Volume: 🔴")
        self.confluence_bb = ctk.CTkLabel(self.confluence_panel, text="Bollinger: 🔴")
        self.confluence_veredito = ctk.CTkLabel(self.confluence_panel, text="Aguardando confluência", font=("Arial", 13, "bold"))
        self.confluence_rsi.pack(side="left", padx=10, pady=8)
        self.confluence_dist.pack(side="left", padx=10, pady=8)
        self.confluence_vol.pack(side="left", padx=10, pady=8)
        self.confluence_bb.pack(side="left", padx=10, pady=8)
        self.confluence_veredito.pack(side="right", padx=10, pady=8)

    def _create_card(self, parent, title: str, value: str):
        card = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=10)
        card.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(card, text=title, text_color="#9ca3af", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(8, 2))
        value_label = ctk.CTkLabel(card, text=value, font=("Arial", 18, "bold"))
        value_label.pack(anchor="w", padx=10, pady=(0, 8))
        return value_label

    def _create_big_card(self, parent, col: int, title: str, value: str):
        card = ctk.CTkFrame(parent, fg_color="#0f172a", corner_radius=10)
        card.grid(row=0, column=col, sticky="nsew", padx=6, pady=(8, 4))
        ctk.CTkLabel(card, text=title, text_color="#9ca3af", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(8, 2))
        value_label = ctk.CTkLabel(card, text=value, font=("Arial", 20, "bold"))
        value_label.pack(anchor="w", padx=10, pady=(0, 8))
        return value_label

    def _criar_grafico_trading(self) -> None:
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.fig.patch.set_facecolor("#1f232a")
        self.ax.set_facecolor("#161a20")
        self.price_line, = self.ax.plot([], [], color="#dbe4ee", linewidth=2.4)
        self.ma_fast_line, = self.ax.plot([], [], color="#22c55e", linewidth=2.2)
        self.ma_slow_line, = self.ax.plot([], [], color="#ef4444", linewidth=2.2)
        self.ax.grid(color="#334155", alpha=0.35, linestyle="-", linewidth=0.8)
        self.ax.tick_params(colors="#cbd5e1")
        self.crosshair_v = self.ax.axvline(0, color="#64748b", linewidth=1.2, alpha=0.9)
        self.crosshair_h = self.ax.axhline(0, color="#64748b", linewidth=1.2, alpha=0.9)
        self.crosshair_text = self.ax.text(
            0.01,
            0.99,
            "",
            transform=self.ax.transAxes,
            ha="left",
            va="top",
            color="#cbd5e1",
            fontsize=9,
            bbox={"facecolor": "#0f172a", "alpha": 0.85, "edgecolor": "#334155"},
        )
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        self.canvas.mpl_connect("motion_notify_event", self._on_chart_hover)

    def _criar_graficos_performance(self) -> None:
        self.perf_fig, (self.perf_ax_equity, self.perf_ax_hist) = plt.subplots(2, 1, figsize=(10, 5))
        self.perf_fig.patch.set_facecolor("#1f232a")
        self.perf_ax_equity.set_facecolor("#161a20")
        self.perf_ax_hist.set_facecolor("#161a20")
        self.perf_equity_line, = self.perf_ax_equity.plot([], [], color="#22c55e", linewidth=2.0, label="Equity")
        self.perf_benchmark_line, = self.perf_ax_equity.plot([], [], color="#94a3b8", linewidth=1.6, label="Benchmark BTC")
        self.perf_ax_equity.legend(loc="upper left")
        self.perf_ax_equity.grid(color="#334155", alpha=0.35)
        self.perf_ax_hist.grid(color="#334155", alpha=0.25)
        self.perf_ax_equity.tick_params(colors="#cbd5e1")
        self.perf_ax_hist.tick_params(colors="#cbd5e1")
        self.perf_canvas = FigureCanvasTkAgg(self.perf_fig, master=self.perf_chart_frame)
        self.perf_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _on_chart_hover(self, event) -> None:
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        self.crosshair_v.set_xdata([event.xdata, event.xdata])
        self.crosshair_h.set_ydata([event.ydata, event.ydata])
        self.crosshair_text.set_text(f"x={event.xdata:.0f}  y={event.ydata:.2f}")
        self.canvas.draw_idle()

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

    def _update_performance_tab(self, snapshot: dict) -> None:
        win_rate = float(snapshot.get("win_rate", 0.0))
        pf = float(snapshot.get("profit_factor", 0.0))
        expectancy = float(snapshot.get("expectancy", 0.0))
        drawdown = float(snapshot.get("current_drawdown_pct", 0.0))
        risk_status = str(snapshot.get("risk_status", "verde")).upper()
        avg_gain = float(snapshot.get("avg_gain", 0.0))
        avg_loss = float(snapshot.get("avg_loss", 0.0))
        equity_history = [float(v) for v in (snapshot.get("equity_history") or [])]
        benchmark_history = [float(v) for v in (snapshot.get("benchmark_history") or [])]
        trades = list(snapshot.get("trade_history") or [])
        near_logs = list(snapshot.get("near_trade_logs") or [])
        confluence = dict(snapshot.get("confluence") or {})

        self.perf_win_rate.configure(text=f"{win_rate * 100:.2f}%")
        self.perf_pf.configure(text=f"{pf:.2f}")
        self.perf_expect.configure(text=f"R$ {expectancy:,.2f}")
        self.perf_dd.configure(text=f"{drawdown:.2f}%")
        risk_color = "#22c55e" if risk_status == "VERDE" else "#f59e0b" if risk_status == "AMARELO" else "#ef4444"
        self.perf_risk.configure(text=risk_status, text_color=risk_color)
        self.expectancy_text.configure(
            text=f"Para cada R$ 1 arriscado, retorno esperado: R$ {expectancy:,.2f} | Avg Gain: R$ {avg_gain:,.2f} | Avg Loss: R$ {avg_loss:,.2f}"
        )

        if equity_history:
            eq = np.array(equity_history)
            self.perf_equity_line.set_data(np.arange(len(eq)), eq)
        else:
            self.perf_equity_line.set_data([], [])

        if benchmark_history and equity_history:
            bm = np.array(benchmark_history[: len(equity_history)])
            if len(bm) > 0 and bm[0] > 0:
                bm_norm = (bm / bm[0]) * equity_history[0]
                self.perf_benchmark_line.set_data(np.arange(len(bm_norm)), bm_norm)
            else:
                self.perf_benchmark_line.set_data([], [])
        else:
            self.perf_benchmark_line.set_data([], [])

        profits = [float(t.get("lucro", 0.0)) for t in trades]
        self.perf_ax_hist.cla()
        self.perf_ax_hist.set_facecolor("#161a20")
        self.perf_ax_hist.tick_params(colors="#cbd5e1")
        self.perf_ax_hist.grid(color="#334155", alpha=0.25)
        if profits:
            self.perf_ax_hist.hist(profits, bins=min(30, max(8, int(len(profits) / 2))), color="#38bdf8", alpha=0.85)
            self.perf_ax_hist.set_title("Histograma de Trades", color="#cbd5e1", fontsize=10)

        self.perf_ax_equity.relim()
        self.perf_ax_equity.autoscale_view()
        self.perf_canvas.draw_idle()

        self._fill_table_box(
            self.deep_logs_box,
            trades[-80:],
            "Data                | Tipo | Entrada   | Saída     | Lucro     | Motivo",
            lambda row: (
                f"{str(row.get('data', ''))[:19]:19} | "
                f"{str(row.get('tipo', '')):4} | "
                f"{float(row.get('entrada', 0.0)):9.2f} | "
                f"{float(row.get('saida', 0.0)):9.2f} | "
                f"{float(row.get('lucro', 0.0)):9.2f} | "
                f"{str(row.get('motivo', ''))[:30]}"
            ),
        )
        self._fill_table_box(
            self.near_trades_box,
            near_logs[-120:],
            "Data                | Motivo                        | SMA9     | SMA21    | SMA50    | RSI   | Vol",
            lambda row: (
                f"{str(row.get('data', ''))[:19]:19} | "
                f"{str(row.get('reason', ''))[:28]:28} | "
                f"{float(row.get('sma9', 0.0)):8.2f} | "
                f"{float(row.get('sma21', 0.0)):8.2f} | "
                f"{float(row.get('sma50', 0.0)):8.2f} | "
                f"{float(row.get('rsi', 0.0)):5.1f} | "
                f"{str(row.get('volume_status', ''))[:8]}"
            ),
        )

        self.confluence_rsi.configure(text=f"RSI: {'🟢' if confluence.get('rsi_ok') else '🔴'}")
        self.confluence_dist.configure(text=f"Distância SMA: {'🟢' if confluence.get('distancia_ok') else '🔴'}")
        self.confluence_vol.configure(text=f"Volume: {'🟢' if confluence.get('volume_ok') else '🔴'}")
        self.confluence_bb.configure(text=f"Bollinger: {'🟢' if confluence.get('bollinger_ok') else '🔴'}")
        self.confluence_veredito.configure(text=str(confluence.get("veredito") or "Aguardando confluência"))

    def _fill_table_box(self, box: ctk.CTkTextbox, rows: list[dict], header: str, formatter) -> None:
        lines = [header, "-" * len(header)]
        lines.extend(formatter(row) for row in rows)
        content = "\n".join(lines) if lines else "-"
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", content)
        box.configure(state="disabled")

    def loop_principal(self) -> None:
        snapshot = self.controller.get_runtime_snapshot()
        self._redesenhar_grafico(float(snapshot.get("price_usdt", 0.0)))
        self._update_performance_tab(snapshot)
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

    def _on_accumulation_toggle(self) -> None:
        self.controller.set_accumulation_mode(self.accumulate_switch.get() == 1)

    def _abrir_janela_simulacao(self) -> None:
        if hasattr(self, "_cfg_window") and self._cfg_window is not None and self._cfg_window.winfo_exists():
            self._cfg_window.focus()
            return
        self._cfg_window = JanelaSimulacao(self, config=self.controller.config, on_save=self._salvar_config_popup, on_start=self._on_start_clicked)

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
        if bool(self.controller.config.get("acumular_saldo", False)):
            self.accumulate_switch.select()
        else:
            self.accumulate_switch.deselect()
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
