from __future__ import annotations

import threading

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
        self._log_lock = threading.Lock()

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
        header.grid_columnconfigure((0, 1, 2, 3), weight=1)
        header.grid_rowconfigure((0, 1), weight=1)

        self.preco_label = ctk.CTkLabel(header, text="BTC/USDT: --", font=("Arial", 14, "bold"))
        self.preco_label.grid(row=0, column=0, sticky="w", padx=16, pady=8)
        self.header_btc_value = ctk.CTkLabel(header, text="$0.00", font=("Arial", 18, "bold"))
        self.header_btc_value.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        self.header_saldo = ctk.CTkLabel(header, text="SALDO\nR$0.00", justify="left", font=("Arial", 14, "bold"))
        self.header_saldo.grid(row=0, column=1, rowspan=2, sticky="w", padx=10, pady=8)
        self.header_drawdown = ctk.CTkLabel(header, text="DRAWDOWN\n0.00%", justify="left", font=("Arial", 14, "bold"))
        self.header_drawdown.grid(row=0, column=2, rowspan=2, sticky="w", padx=10, pady=8)
        self.header_strategy = ctk.CTkLabel(header, text="ESTRATEGIA\nAUTO", justify="left", font=("Arial", 14, "bold"))
        self.header_strategy.grid(row=0, column=3, rowspan=1, sticky="w", padx=10, pady=(8, 2))
        self.header_fees = ctk.CTkLabel(header, text="TAXAS\nR$0.00", justify="left", font=("Arial", 12, "bold"))
        self.header_fees.grid(row=1, column=2, sticky="w", padx=10, pady=(0, 10))
        self.header_position = ctk.CTkLabel(header, text="POSICAO\nNONE", justify="left", font=("Arial", 12, "bold"))
        self.header_position.grid(row=1, column=3, sticky="w", padx=10, pady=(0, 10))

        self.tabs = ctk.CTkTabview(self, fg_color="#161a20")
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.tab_trading = self.tabs.add("Trading")
        self.tab_performance = self.tabs.add("Performance")
        self.tab_registro = self.tabs.add("Registro Mensal")

        self._criar_tab_trading()
        self._criar_tab_performance()
        self._criar_tab_registro()

    def _criar_tab_trading(self) -> None:
        self.tab_trading.grid_columnconfigure(0, weight=4)
        self.tab_trading.grid_columnconfigure(1, weight=1)
        self.tab_trading.grid_rowconfigure(0, weight=0)
        self.tab_trading.grid_rowconfigure(1, weight=5)
        self.tab_trading.grid_rowconfigure(2, weight=1)

        self.header_frame = ctk.CTkFrame(self.tab_trading, fg_color="#1f232a", corner_radius=14)
        self.header_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)
        ctk.CTkLabel(self.header_frame, text="CONTROLE DO BOT", font=("Arial", 17, "bold")).pack(pady=(12, 10))

        self.graph_frame = ctk.CTkFrame(self.tab_trading, fg_color="#1f232a", corner_radius=14)
        self.graph_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)

        self.side_panel = ctk.CTkFrame(self.tab_trading, fg_color="#1f232a", corner_radius=14)
        self.side_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
        self.side_panel.configure(width=320)
        self.side_panel.grid_propagate(False)
        side = self.side_panel

        ctk.CTkLabel(side, text="Configuração", font=("Arial", 15, "bold")).pack(pady=(10, 8))
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

        ctk.CTkLabel(side, text="Modo de Trading", anchor="w").pack(fill="x", padx=16)
        self.strategy_mode_switch = ctk.CTkSegmentedButton(
            side,
            values=["TENDENCIA", "LATERAL", "AUTO"],
            command=self._on_strategy_mode_change,
        )
        self.strategy_mode_switch.pack(fill="x", padx=16, pady=(6, 10))

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
        self.config_button.pack(fill="x", padx=16, pady=(0, 8))
        self.download_logs_button = ctk.CTkButton(
            side,
            text="Download Logs",
            height=36,
            fg_color="#1d4ed8",
            hover_color="#1e40af",
            command=self._on_download_logs_clicked,
        )
        self.download_logs_button.pack(fill="x", padx=16, pady=(0, 14))

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

        self.log_frame = ctk.CTkFrame(self.tab_trading, fg_color="#0b1220", corner_radius=12)
        self.log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(5, 10))
        self.log_frame.configure(height=100)
        self.log_frame.grid_propagate(False)
        ctk.CTkLabel(self.log_frame, text="Console de Logs", font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        self.console_box = ctk.CTkTextbox(self.log_frame, height=70, state="disabled")
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

        self.perf_total_trades = self._create_big_card(zone1, 0, "Total de Trades", "0")
        self.perf_win_rate = self._create_big_card(zone1, 1, "Win Rate", "0.00%")
        self.perf_lucro_liquido = self._create_big_card(zone1, 2, "Lucro Líquido", "R$ 0.00")
        self.perf_dd_max = self._create_big_card(zone1, 3, "Drawdown Máximo", "0.00%")
        self.perf_pf = self._create_big_card(zone1, 4, "Profit Factor", "0.00")
        self.expectancy_text = ctk.CTkLabel(zone1, text="Resumo em tempo real da simulação", anchor="w")
        self.expectancy_text.grid(row=1, column=0, columnspan=5, sticky="ew", padx=12, pady=(2, 8))
        self.cross_stats_text = ctk.CTkLabel(
            zone1,
            text="Cross total: 0 | Filtrados: 0 | Executados: 0 | Trades +: 0 | Trades -: 0",
            anchor="w",
        )
        self.cross_stats_text.grid(row=2, column=0, columnspan=5, sticky="ew", padx=12, pady=(0, 8))

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
        self.confluence_rsi = ctk.CTkLabel(self.confluence_panel, text="EMA9>EMA21: 🔴")
        self.confluence_dist = ctk.CTkLabel(self.confluence_panel, text="Slope EMA9: 🔴")
        self.confluence_vol = ctk.CTkLabel(self.confluence_panel, text="ATR Gate: 🔴")
        self.confluence_bb = ctk.CTkLabel(self.confluence_panel, text="Regime: LATERAL")
        self.confluence_veredito = ctk.CTkLabel(self.confluence_panel, text="Aguardando confluencia", font=("Arial", 13, "bold"))
        self.confluence_rsi.pack(side="left", padx=10, pady=8)
        self.confluence_dist.pack(side="left", padx=10, pady=8)
        self.confluence_vol.pack(side="left", padx=10, pady=8)
        self.confluence_bb.pack(side="left", padx=10, pady=8)
        self.confluence_veredito.pack(side="right", padx=10, pady=8)

    def _criar_tab_registro(self) -> None:
        root = ctk.CTkFrame(self.tab_registro, fg_color="#161a20")
        root.pack(fill="both", expand=True, padx=8, pady=8)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=1)

        self.registro_cards = ctk.CTkFrame(root, fg_color="#1f232a", corner_radius=12)
        self.registro_cards.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.registro_cards.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        self.reg_lucro_mes = self._create_big_card(self.registro_cards, 0, "Lucro do mês", "R$ 0.00")
        self.reg_trades = self._create_big_card(self.registro_cards, 1, "Trades executados", "0")
        self.reg_sessoes = self._create_big_card(self.registro_cards, 2, "Sessões do bot", "0")
        self.reg_best = self._create_big_card(self.registro_cards, 3, "Melhor dia", "R$ 0.00")
        self.reg_worst = self._create_big_card(self.registro_cards, 4, "Pior dia", "R$ 0.00")

        self.reg_table = ctk.CTkTextbox(root, state="disabled")
        self.reg_table.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.reg_chart = ctk.CTkTextbox(root, state="disabled")
        self.reg_chart.grid(row=2, column=0, sticky="nsew")

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
        self.fig.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
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
        drawdown_max = float(snapshot.get("drawdown_max_pct", 0.0))
        avg_gain = float(snapshot.get("avg_gain", 0.0))
        avg_loss = float(snapshot.get("avg_loss", 0.0))
        total_trades_snap = int(snapshot.get("total_trades", 0) or 0)
        lucro_liquido = float(snapshot.get("lucro_liquido_brl", 0.0))
        equity_history = [float(v) for v in (snapshot.get("equity_history") or [])]
        benchmark_history = [float(v) for v in (snapshot.get("benchmark_history") or [])]
        trades = list(snapshot.get("trade_history") or [])
        near_logs = list(snapshot.get("near_trade_logs") or [])
        confluence = dict(snapshot.get("confluence") or {})
        total_cross = int(snapshot.get("total_cross", 0) or 0)
        cross_filtrados = int(snapshot.get("cross_filtrados", 0) or 0)
        cross_executados = int(snapshot.get("cross_executados", 0) or 0)
        trades_lucrativos = int(snapshot.get("trades_lucrativos", 0) or 0)
        trades_prejuizo = int(snapshot.get("trades_prejuizo", 0) or 0)

        self.perf_total_trades.configure(text=f"{total_trades_snap}")
        self.perf_win_rate.configure(text=f"{win_rate * 100:.2f}%")
        self.perf_pf.configure(text=f"{pf:.2f}")
        self.perf_lucro_liquido.configure(text=f"R$ {lucro_liquido:,.2f}")
        self.perf_dd_max.configure(text=f"{drawdown_max:.2f}%")
        self.expectancy_text.configure(
            text=f"Atualização em tempo real | Avg Gain: R$ {avg_gain:,.2f} | Avg Loss: R$ {avg_loss:,.2f}"
        )
        self.cross_stats_text.configure(
            text=(
                f"Cross total: {total_cross} | Filtrados: {cross_filtrados} | Executados: {cross_executados} | "
                f"Trades +: {trades_lucrativos} | Trades -: {trades_prejuizo}"
            )
        )

        self.perf_ax_equity.cla()
        self.perf_ax_equity.set_facecolor("#161a20")
        self.perf_ax_equity.tick_params(colors="#cbd5e1")
        self.perf_ax_equity.grid(color="#334155", alpha=0.35)
        if equity_history:
            eq = np.array(equity_history)
            x = np.arange(len(eq))
            self.perf_ax_equity.plot(x, eq, color="#22c55e", linewidth=2.0, label="Equity")
            peak = np.maximum.accumulate(eq)
            self.perf_ax_equity.fill_between(x, eq, peak, where=peak >= eq, color="#ef4444", alpha=0.15, label="Drawdown")
            if benchmark_history:
                bm = np.array(benchmark_history[: len(equity_history)])
                if len(bm) > 0 and bm[0] > 0:
                    bm_norm = (bm / bm[0]) * equity_history[0]
                    self.perf_ax_equity.plot(np.arange(len(bm_norm)), bm_norm, color="#94a3b8", linewidth=1.6, label="Benchmark BTC")
        self.perf_ax_equity.legend(loc="upper left")

        profits = [float(t.get("lucro", 0.0)) for t in trades]
        self.perf_ax_hist.cla()
        self.perf_ax_hist.set_facecolor("#161a20")
        self.perf_ax_hist.tick_params(colors="#cbd5e1")
        self.perf_ax_hist.grid(color="#334155", alpha=0.25)
        if profits:
            self.perf_ax_hist.hist(profits, bins=min(30, max(8, int(len(profits) / 2))), color="#38bdf8", alpha=0.85)
            self.perf_ax_hist.set_title("Histograma de Trades", color="#cbd5e1", fontsize=10)

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
            "Data                | BTC       | EMA9     | EMA21    | Dist%    | Slope    | Motivo",
            lambda row: (
                f"{str(row.get('data', ''))[:19]:19} | "
                f"{float(row.get('price_btc', 0.0)):9.2f} | "
                f"{float(row.get('ema9', 0.0)):8.2f} | "
                f"{float(row.get('ema21', 0.0)):8.2f} | "
                f"{float(row.get('distancia_percentual', 0.0)):9.5%} | "
                f"{float(row.get('slope', 0.0)):8.4f} | "
                f"{str(row.get('reason', ''))[:32]:32}"
            ),
        )

        self.confluence_rsi.configure(text=f"EMA9>EMA21: {'🟢' if confluence.get('ema_above_sma') else '🔴'}")
        self.confluence_dist.configure(text=f"Slope EMA9: {'🟢' if confluence.get('sma_slope_up') else '🔴'}")
        self.confluence_vol.configure(text=f"ATR Gate: {'🟢' if confluence.get('distancia_ok') else '🔴'}")
        self.confluence_bb.configure(text=f"Regime: {str(snapshot.get('strategy_mode_active', 'lateral')).upper()}")
        self.confluence_veredito.configure(text=str(confluence.get("veredito") or "Aguardando confluencia"))
        self._update_registro_tab(snapshot)

    def _update_registro_tab(self, snapshot: dict) -> None:
        trades = list(snapshot.get("trade_history") or [])
        self.reg_lucro_mes.configure(text=f"R$ {float(snapshot.get('monthly_profit', 0.0)):,.2f}")
        self.reg_trades.configure(text=f"{int(snapshot.get('trades_count_db', 0) or 0)}")
        self.reg_sessoes.configure(text=f"{int(snapshot.get('sessions_count', 0) or 0)}")
        self.reg_best.configure(text=f"R$ {float(snapshot.get('best_day', 0.0)):,.2f}")
        self.reg_worst.configure(text=f"R$ {float(snapshot.get('worst_day', 0.0)):,.2f}")

        lines = ["Data       | Trades | Lucro dia | Taxas | Saldo final", "-" * 58]
        by_day: dict[str, dict[str, float]] = {}
        for t in trades:
            day = str(t.get("data", ""))[:10]
            if not day:
                continue
            row = by_day.setdefault(day, {"trades": 0.0, "lucro": 0.0})
            row["trades"] += 1
            row["lucro"] += float(t.get("lucro", 0.0))
        for day, vals in sorted(by_day.items(), reverse=True):
            lines.append(f"{day:10} | {int(vals['trades']):6d} | {vals['lucro']:9.2f} | {'-':5} | {'-':11}")
        self._set_textbox_content(self.reg_table, "\n".join(lines))

        cum = 0.0
        chart_lines = ["Lucro acumulado do mes", "-" * 28]
        for day, vals in sorted(by_day.items()):
            cum += float(vals["lucro"])
            chart_lines.append(f"{day}: {cum:+.2f}")
        self._set_textbox_content(self.reg_chart, "\n".join(chart_lines))

    def _fill_table_box(self, box: ctk.CTkTextbox, rows: list[dict], header: str, formatter) -> None:
        lines = [header, "-" * len(header)]
        lines.extend(formatter(row) for row in rows)
        content = "\n".join(lines) if lines else "-"
        self._set_textbox_content(box, content)

    def _set_textbox_content(self, box: ctk.CTkTextbox, content: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", content)
        box.see("end")
        box.configure(state="disabled")

    def loop_principal(self) -> None:
        self._flush_pending_logs()
        snapshot = self.controller.get_runtime_snapshot()
        self._redesenhar_grafico(float(snapshot.get("price_usdt", 0.0)))
        self._update_performance_tab(snapshot)
        self.bridge.update_dashboard(snapshot)
        self.after(1000, self.loop_principal)

    def _on_start_clicked(self) -> None:
        print("BOTAO START CLICADO")
        result = self.controller.start()
        print("RESULTADO START:", result)
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

    def _on_strategy_mode_change(self, value: str) -> None:
        mode_map = {"TENDENCIA": "tendencia", "LATERAL": "lateral", "AUTO": "auto"}
        self.controller.set_trading_mode(mode_map.get(str(value).upper(), "auto"))

    def _on_download_logs_clicked(self) -> None:
        ok, path_or_err = self.controller.download_logs_report()
        if ok:
            self.bridge.log_message(f"Relatorio gerado: {path_or_err}")
        else:
            self.bridge.log_message(f"Falha ao gerar relatorio: {path_or_err}")

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
        strategy_mode = str(self.controller.config.get("trading_mode", "auto")).upper()
        if strategy_mode not in {"TENDENCIA", "LATERAL", "AUTO"}:
            strategy_mode = "AUTO"
        self.strategy_mode_switch.set(strategy_mode)
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
        with self._log_lock:
            self._pending_logs.append(msg)

    def _flush_pending_logs(self) -> None:
        with self._log_lock:
            logs = list(self._pending_logs)
            self._pending_logs.clear()
        for msg in logs:
            self.bridge.log_message(msg)

    def _on_close(self) -> None:
        self.controller.shutdown()
        self.destroy()


class MainWindow(TradingApp):
    pass
