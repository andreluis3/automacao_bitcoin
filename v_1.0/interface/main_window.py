"""
main_window.py — Janela principal da Automação Bitcoin.

Melhorias v3:
  - Indicador de conexão (🟢/🟡/🔴) com reconexão automática
  - Cache do último snapshot válido (fallback offline)
  - Timeout configurável na coleta de preço
  - Loop principal com proteção contra lag de rede
  - TabPerformance e Registro Mensal com muito mais dados
  - Código morto removido (MainWindow herdava TradingApp sem necessidade)
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from interface.bot_controller import BotController
from interface.janela_simulacao import JanelaSimulacao
from interface.ui_bridge import UIBridge

ctk.set_appearance_mode("dark")

# ── Paleta ────────────────────────────────────────────────────────────────────
APP_BG     = "#0d1117"
CARD_BG    = "#161b22"
CARD_BG2   = "#1c2128"
BORDER     = "#30363d"
GREEN      = "#22c55e"
RED        = "#ef4444"
YELLOW     = "#f59e0b"
BLUE       = "#38bdf8"
TEXT_PRI   = "#e6edf3"
TEXT_SEC   = "#8b949e"
ACCENT     = "#1f6feb"

# ── Constantes de resiliência ──────────────────────────────────────────────────
_SNAPSHOT_TIMEOUT_SEC   = 5.0   # máximo para obter snapshot
_OFFLINE_WARN_TICKS     = 3     # ticks sem dados → amarelo
_OFFLINE_ERROR_TICKS    = 8     # ticks sem dados → vermelho


class TradingApp(ctk.CTk):
    def __init__(self, market_data):
        super().__init__()
        self.title("Automação Bitcoin")
        self.geometry("1400x920")
        self.configure(fg_color=APP_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = BotController(
            market_data=market_data,
            log_callback=self._enqueue_log,
        )
        self.bridge = UIBridge(self)

        # Estado interno
        self._pending_logs: list[str] = []
        self._log_lock = threading.Lock()
        self.max_candles = 240
        self.prices: list[float] = []

        # Resiliência de conexão
        self._last_valid_snapshot: dict[str, Any] = {}
        self._ticks_sem_dados: int = 0
        self._connection_state: str = "ok"   # "ok" | "warn" | "error"
        self._snapshot_lock = threading.Lock()

        self._criar_layout()
        self._criar_grafico_trading()
        self._criar_graficos_performance()
        self._criar_graficos_registro()
        self._aplicar_config_inicial_ui()
        self._flush_pending_logs()
        self._atualizar_lock_real()
        self.after(400, self.loop_principal)

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT PRINCIPAL
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_layout(self) -> None:
        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=0, border_width=0)
        header.pack(fill="x", padx=0, pady=0)
        header.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        # Coluna 0 — preço + variação
        col0 = ctk.CTkFrame(header, fg_color="transparent")
        col0.grid(row=0, column=0, sticky="w", padx=20, pady=12)
        self.preco_label = ctk.CTkLabel(col0, text="BTC/USDT: --",
                                        font=("JetBrains Mono", 13, "bold"), text_color=TEXT_SEC)
        self.preco_label.pack(anchor="w")
        self.header_btc_value = ctk.CTkLabel(col0, text="$0.00",
                                             font=("JetBrains Mono", 22, "bold"), text_color=TEXT_PRI)
        self.header_btc_value.pack(anchor="w")

        # Coluna 1 — saldo
        self.header_saldo = self._header_card(header, 1, "SALDO", "R$ 0.00")

        # Coluna 2 — drawdown
        self.header_drawdown = self._header_card(header, 2, "DRAWDOWN", "0.00%")

        # Coluna 3 — estratégia/posição
        self.header_strategy = self._header_card(header, 3, "ESTRATÉGIA", "AUTO/LATERAL")

        # Coluna 4 — conexão + taxas
        col4 = ctk.CTkFrame(header, fg_color="transparent")
        col4.grid(row=0, column=4, sticky="e", padx=20, pady=12)
        self.conn_label = ctk.CTkLabel(col4, text="● ONLINE",
                                       font=("JetBrains Mono", 11, "bold"), text_color=GREEN)
        self.conn_label.pack(anchor="e")
        self.header_fees = ctk.CTkLabel(col4, text="TAXAS  R$ 0.00",
                                        font=("JetBrains Mono", 11), text_color=TEXT_SEC)
        self.header_fees.pack(anchor="e", pady=(4, 0))
        self.header_position = ctk.CTkLabel(col4, text="POSICAO  ● NONE",
                                            font=("JetBrains Mono", 11), text_color=TEXT_SEC)
        self.header_position.pack(anchor="e", pady=(2, 0))

        # ── Tabs ──────────────────────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(self, fg_color=APP_BG, segmented_button_fg_color=CARD_BG,
                                   segmented_button_selected_color=ACCENT,
                                   segmented_button_unselected_color=CARD_BG)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(8, 12))

        self.tab_trading     = self.tabs.add("Trading")
        self.tab_performance = self.tabs.add("Performance")
        self.tab_registro    = self.tabs.add("Registro Mensal")

        self._criar_tab_trading()
        self._criar_tab_performance()
        self._criar_tab_registro()

    def _header_card(self, parent, col: int, title: str, value: str) -> ctk.CTkLabel:
        """Cria uma célula do header e retorna o label do valor."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, padx=10, pady=12, sticky="w")
        ctk.CTkLabel(frame, text=title, font=("JetBrains Mono", 10), text_color=TEXT_SEC).pack(anchor="w")
        lbl = ctk.CTkLabel(frame, text=value, font=("JetBrains Mono", 16, "bold"), text_color=TEXT_PRI)
        lbl.pack(anchor="w")
        return lbl

    # ══════════════════════════════════════════════════════════════════════════
    # TAB TRADING
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_tab_trading(self) -> None:
        self.tab_trading.grid_columnconfigure(0, weight=4)
        self.tab_trading.grid_columnconfigure(1, weight=1)
        self.tab_trading.grid_rowconfigure(0, weight=0)
        self.tab_trading.grid_rowconfigure(1, weight=5)
        self.tab_trading.grid_rowconfigure(2, weight=1)

        # Título
        tit = ctk.CTkFrame(self.tab_trading, fg_color=CARD_BG, corner_radius=12)
        tit.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 6))
        ctk.CTkLabel(tit, text="CONTROLE DO BOT",
                     font=("JetBrains Mono", 15, "bold"), text_color=TEXT_PRI).pack(pady=(10, 8))

        # Gráfico
        self.graph_frame = ctk.CTkFrame(self.tab_trading, fg_color=CARD_BG, corner_radius=12)
        self.graph_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 4), pady=4)

        # Painel lateral
        self.side_panel = ctk.CTkScrollableFrame(self.tab_trading, fg_color=CARD_BG, corner_radius=12, width=300)
        self.side_panel.grid(row=1, column=1, sticky="nsew", padx=(4, 6), pady=4)
        self._criar_painel_lateral(self.side_panel)

        # Console
        self.log_frame = ctk.CTkFrame(self.tab_trading, fg_color="#080d13", corner_radius=10)
        self.log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=6, pady=(4, 6))
        self.log_frame.configure(height=90)
        self.log_frame.grid_propagate(False)
        ctk.CTkLabel(self.log_frame, text="Console de Logs",
                     font=("JetBrains Mono", 11, "bold"), text_color=TEXT_SEC).pack(anchor="w", padx=12, pady=(6, 2))
        self.console_box = ctk.CTkTextbox(self.log_frame, height=55, state="disabled",
                                          font=("JetBrains Mono", 11), fg_color="#080d13", text_color=TEXT_PRI)
        self.console_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    def _criar_painel_lateral(self, side) -> None:
        ctk.CTkLabel(side, text="Configuração",
                     font=("JetBrains Mono", 13, "bold"), text_color=TEXT_PRI).pack(pady=(10, 6))

        # Status LED
        status_row = ctk.CTkFrame(side, fg_color="transparent")
        status_row.pack(fill="x", padx=12, pady=(0, 8))
        self.led_status   = ctk.CTkLabel(status_row, text="●", font=("Segoe UI", 22), text_color="#6b7280")
        self.led_status.pack(side="left")
        self.badge_status = ctk.CTkLabel(status_row, text="PARADO",
                                         font=("JetBrains Mono", 12, "bold"), text_color=TEXT_PRI)
        self.badge_status.pack(side="left", padx=(8, 0))

        # Modo
        ctk.CTkLabel(side, text="Modo", anchor="w", text_color=TEXT_SEC,
                     font=("JetBrains Mono", 11)).pack(fill="x", padx=12)
        self.mode_switch = ctk.CTkSegmentedButton(side, values=["SIMULACAO", "REAL"],
                                                   command=self._on_mode_change,
                                                   fg_color=CARD_BG2, selected_color=ACCENT)
        self.mode_switch.pack(fill="x", padx=12, pady=(4, 4))
        self.lock_label = ctk.CTkLabel(side, text="", text_color=YELLOW,
                                       font=("JetBrains Mono", 10, "bold"))
        self.lock_label.pack(anchor="w", padx=12, pady=(0, 6))

        # Modo de Trading
        ctk.CTkLabel(side, text="Modo de Trading", anchor="w", text_color=TEXT_SEC,
                     font=("JetBrains Mono", 11)).pack(fill="x", padx=12)
        self.strategy_mode_switch = ctk.CTkSegmentedButton(
            side, values=["TENDENCIA", "LATERAL", "AUTO"],
            command=self._on_strategy_mode_change,
            fg_color=CARD_BG2, selected_color=ACCENT,
        )
        self.strategy_mode_switch.pack(fill="x", padx=12, pady=(4, 8))

        # Perfil
        ctk.CTkLabel(side, text="Perfil", anchor="w", text_color=TEXT_SEC,
                     font=("JetBrains Mono", 11)).pack(fill="x", padx=12)
        self.profile_combo = ctk.CTkComboBox(side, values=["Conservador", "Agressivo"],
                                              state="readonly", command=self._on_profile_change,
                                              fg_color=CARD_BG2, border_color=BORDER)
        self.profile_combo.pack(fill="x", padx=12, pady=(4, 10))

        # Botões
        self.start_button = ctk.CTkButton(side, text="INICIAR", height=40,
                                           fg_color="#166534", hover_color="#15803d",
                                           font=("JetBrains Mono", 13, "bold"),
                                           command=self._on_start_clicked)
        self.start_button.pack(fill="x", padx=12, pady=(2, 6))

        self.stop_button = ctk.CTkButton(side, text="PARAR", height=40,
                                          fg_color="#7f1d1d", hover_color="#b91c1c",
                                          font=("JetBrains Mono", 13, "bold"),
                                          command=self._on_stop_clicked)
        self.stop_button.pack(fill="x", padx=12, pady=(0, 6))

        self.config_button = ctk.CTkButton(side, text="⚙ Configurações", height=34,
                                            fg_color=CARD_BG2, hover_color=BORDER,
                                            font=("JetBrains Mono", 11),
                                            command=self._abrir_janela_simulacao)
        self.config_button.pack(fill="x", padx=12, pady=(0, 6))

        self.download_logs_button = ctk.CTkButton(side, text="Download Logs", height=34,
                                                   fg_color="#1e3a5f", hover_color="#1e40af",
                                                   font=("JetBrains Mono", 11),
                                                   command=self._on_download_logs_clicked)
        self.download_logs_button.pack(fill="x", padx=12, pady=(0, 10))

        self.accumulate_switch = ctk.CTkSwitch(side, text="Ativar Acumulação",
                                                font=("JetBrains Mono", 11),
                                                progress_color=ACCENT,
                                                command=self._on_accumulation_toggle)
        self.accumulate_switch.pack(anchor="w", padx=12, pady=(0, 8))

        # Cards de métricas
        cards = ctk.CTkFrame(side, fg_color=APP_BG, corner_radius=10)
        cards.pack(fill="x", padx=12, pady=(2, 10))

        self.card_lucro_value             = self._mini_card(cards, "Lucro Hoje",           "R$ 0.00")
        self.card_equity_value            = self._mini_card(cards, "Equity Atual",          "R$ 0.00")
        self.card_reserva_value           = self._mini_card(cards, "Reserva Segura",        "R$ 0.00")
        self.card_exposicao_value         = self._mini_card(cards, "Exposição",             "R$ 0.00 (0%)")
        self.card_profit_factor_value     = self._mini_card(cards, "Profit Factor",         "0.00")
        self.card_patrimonio_protegido_value = self._mini_card(cards, "Patrimônio Protegido", "R$ 0.00")
        self.card_drawdown_value          = self._mini_card(cards, "Drawdown",              "0.00%")
        self.card_alerta_value = ctk.CTkLabel(cards, text="", text_color=YELLOW,
                                              font=("JetBrains Mono", 10, "bold"))
        self.card_alerta_value.pack(anchor="w", padx=10, pady=(4, 4))
        self.drawdown_progress = ctk.CTkProgressBar(cards, progress_color=RED, height=6)
        self.drawdown_progress.set(0)
        self.drawdown_progress.pack(fill="x", padx=10, pady=(0, 10))

    def _mini_card(self, parent, title: str, value: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(row, text=title, text_color=TEXT_SEC,
                     font=("JetBrains Mono", 10)).pack(side="left")
        lbl = ctk.CTkLabel(row, text=value, font=("JetBrains Mono", 12, "bold"), text_color=TEXT_PRI)
        lbl.pack(side="right")
        return lbl

    # ══════════════════════════════════════════════════════════════════════════
    # TAB PERFORMANCE — reformulada com muito mais dados
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_tab_performance(self) -> None:
        root = self.tab_performance
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=2)
        root.grid_rowconfigure(2, weight=1)

        # ── Zona 1: KPIs ──────────────────────────────────────────────────────
        z1 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z1.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 6))
        z1.grid_columnconfigure((0,1,2,3,4,5,6), weight=1)

        kpis = [
            ("perf_total_trades",   "Total Trades",      "0"),
            ("perf_win_rate",       "Win Rate",          "0.00%"),
            ("perf_lucro_liquido",  "Lucro Líquido",     "R$ 0.00"),
            ("perf_dd_max",         "Drawdown Máx",      "0.00%"),
            ("perf_pf",             "Profit Factor",     "0.00"),
            ("perf_sharpe",         "Sharpe",            "0.00"),
            ("perf_expectancy",     "Expectância",       "R$ 0.00"),
        ]
        for idx, (attr, title, val) in enumerate(kpis):
            card = ctk.CTkFrame(z1, fg_color=CARD_BG2, corner_radius=10)
            card.grid(row=0, column=idx, sticky="nsew", padx=5, pady=8)
            ctk.CTkLabel(card, text=title, text_color=TEXT_SEC,
                         font=("JetBrains Mono", 10)).pack(anchor="w", padx=10, pady=(8,2))
            lbl = ctk.CTkLabel(card, text=val, font=("JetBrains Mono", 18, "bold"), text_color=TEXT_PRI)
            lbl.pack(anchor="w", padx=10, pady=(0, 8))
            setattr(self, attr, lbl)

        # Stats de cross
        self.expectancy_text = ctk.CTkLabel(z1, text="Avg Gain: R$0.00 | Avg Loss: R$0.00",
                                             anchor="w", text_color=TEXT_SEC,
                                             font=("JetBrains Mono", 10))
        self.expectancy_text.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 6))
        self.cross_stats_text = ctk.CTkLabel(
            z1, text="Cross: 0 | Filtrados: 0 | Executados: 0 | ✔ 0 | ✖ 0",
            anchor="w", text_color=TEXT_SEC, font=("JetBrains Mono", 10))
        self.cross_stats_text.grid(row=1, column=4, columnspan=3, sticky="ew", padx=14, pady=(0, 6))

        # ── Zona 2: Gráficos ──────────────────────────────────────────────────
        z2 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z2.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.perf_chart_frame = ctk.CTkFrame(z2, fg_color=CARD_BG)
        self.perf_chart_frame.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Zona 3: Deep logs + Quase-Trades + Confluência ────────────────────
        z3 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z3.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        z3.grid_columnconfigure(0, weight=2)
        z3.grid_columnconfigure(1, weight=1)
        z3.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(z3, text="Deep Logs", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).grid(row=0, column=0, sticky="w", padx=12, pady=(8,4))
        ctk.CTkLabel(z3, text="Quase-Trades", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).grid(row=0, column=1, sticky="w", padx=12, pady=(8,4))

        self.deep_logs_box = ctk.CTkTextbox(z3, state="disabled",
                                             font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self.deep_logs_box.grid(row=1, column=0, sticky="nsew", padx=(10,4), pady=(0,8))

        self.near_trades_box = ctk.CTkTextbox(z3, state="disabled",
                                               font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self.near_trades_box.grid(row=1, column=1, sticky="nsew", padx=(4,10), pady=(0,8))

        # Confluência
        self.confluence_panel = ctk.CTkFrame(z3, fg_color=APP_BG, corner_radius=8)
        self.confluence_panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        self.confluence_rsi  = ctk.CTkLabel(self.confluence_panel, text="EMA9>EMA21: 🔴",
                                             font=("JetBrains Mono", 11))
        self.confluence_dist = ctk.CTkLabel(self.confluence_panel, text="Slope EMA9: 🔴",
                                             font=("JetBrains Mono", 11))
        self.confluence_vol  = ctk.CTkLabel(self.confluence_panel, text="ATR Gate: 🔴",
                                             font=("JetBrains Mono", 11))
        self.confluence_bb   = ctk.CTkLabel(self.confluence_panel, text="Regime: LATERAL",
                                             font=("JetBrains Mono", 11))
        self.confluence_veredito = ctk.CTkLabel(self.confluence_panel, text="Aguardando confluencia",
                                                 font=("JetBrains Mono", 12, "bold"), text_color=YELLOW)
        for lbl in (self.confluence_rsi, self.confluence_dist, self.confluence_vol, self.confluence_bb):
            lbl.pack(side="left", padx=12, pady=6)
        self.confluence_veredito.pack(side="right", padx=12, pady=6)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB REGISTRO MENSAL — reformulada com gráficos e tabela rica
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_tab_registro(self) -> None:
        root = self.tab_registro
        root.grid_columnconfigure(0, weight=3)
        root.grid_columnconfigure(1, weight=2)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=2)

        # ── Zona 0: KPIs mensais ──────────────────────────────────────────────
        z0 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z0.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 6))
        z0.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        reg_kpis = [
            ("reg_lucro_mes",  "Lucro do Mês",     "R$ 0.00"),
            ("reg_trades",     "Trades Executados", "0"),
            ("reg_sessoes",    "Sessões do Bot",    "0"),
            ("reg_best",       "Melhor Dia",        "R$ 0.00"),
            ("reg_worst",      "Pior Dia",          "R$ 0.00"),
            ("reg_avg_trade",  "Média por Trade",   "R$ 0.00"),
        ]
        for idx, (attr, title, val) in enumerate(reg_kpis):
            card = ctk.CTkFrame(z0, fg_color=CARD_BG2, corner_radius=10)
            card.grid(row=0, column=idx, sticky="nsew", padx=5, pady=8)
            ctk.CTkLabel(card, text=title, text_color=TEXT_SEC,
                         font=("JetBrains Mono", 10)).pack(anchor="w", padx=10, pady=(8,2))
            lbl = ctk.CTkLabel(card, text=val, font=("JetBrains Mono", 16, "bold"), text_color=TEXT_PRI)
            lbl.pack(anchor="w", padx=10, pady=(0,8))
            setattr(self, attr, lbl)

        # ── Zona 1: Tabela diária ──────────────────────────────────────────────
        z1 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z1.grid(row=1, column=0, sticky="nsew", padx=(6,4), pady=(0,6))
        ctk.CTkLabel(z1, text="Registro Diário", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).pack(anchor="w", padx=12, pady=(8,4))
        self.reg_table = ctk.CTkTextbox(z1, state="disabled",
                                         font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self.reg_table.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # ── Zona 1b: Detalhes de posição ──────────────────────────────────────
        z1b = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z1b.grid(row=1, column=1, sticky="nsew", padx=(4,6), pady=(0,6))
        ctk.CTkLabel(z1b, text="Detalhes de Performance", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).pack(anchor="w", padx=12, pady=(8,4))
        self.reg_details = ctk.CTkTextbox(z1b, state="disabled",
                                           font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self.reg_details.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # ── Zona 2: Gráfico de lucro acumulado (matplotlib) ───────────────────
        z2 = ctk.CTkFrame(root, fg_color=CARD_BG, corner_radius=12)
        z2.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0,6))
        ctk.CTkLabel(z2, text="Lucro Acumulado no Mês", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).pack(anchor="w", padx=12, pady=(8,4))
        self.reg_chart_frame = ctk.CTkFrame(z2, fg_color=CARD_BG)
        self.reg_chart_frame.pack(fill="both", expand=True, padx=8, pady=(0,8))

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICOS MATPLOTLIB
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_grafico_trading(self) -> None:
        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_facecolor(APP_BG)
        self.price_line,  = self.ax.plot([], [], color=TEXT_PRI, linewidth=2.0, label="BTC")
        self.ma_fast_line,= self.ax.plot([], [], color=GREEN,    linewidth=1.5, label="EMA9")
        self.ma_slow_line,= self.ax.plot([], [], color=RED,      linewidth=1.5, label="EMA21")
        self.ax.tick_params(colors=TEXT_SEC, labelsize=8)
        self.ax.grid(color=BORDER, alpha=0.4, linestyle="--", linewidth=0.6)
        self.ax.legend(loc="upper left", fontsize=8, facecolor=CARD_BG,
                       labelcolor=TEXT_PRI, framealpha=0.8)
        self.fig.subplots_adjust(left=0.06, right=0.98, top=0.94, bottom=0.10)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

    def _criar_graficos_performance(self) -> None:
        self.perf_fig, (self.perf_ax_equity, self.perf_ax_hist) = plt.subplots(
            1, 2, figsize=(12, 4), gridspec_kw={"width_ratios": [3, 1]}
        )
        self.perf_fig.patch.set_facecolor(CARD_BG)
        for ax in (self.perf_ax_equity, self.perf_ax_hist):
            ax.set_facecolor(APP_BG)
            ax.tick_params(colors=TEXT_SEC, labelsize=8)
            ax.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)

        self.perf_equity_line,    = self.perf_ax_equity.plot([], [], color=GREEN, linewidth=2.0, label="Equity")
        self.perf_benchmark_line, = self.perf_ax_equity.plot([], [], color=TEXT_SEC, linewidth=1.2,
                                                               label="Benchmark BTC", linestyle="--")
        self.perf_ax_equity.legend(loc="upper left", fontsize=8, facecolor=CARD_BG,
                                    labelcolor=TEXT_PRI, framealpha=0.8)
        self.perf_ax_equity.set_title("Equity vs Benchmark", color=TEXT_PRI, fontsize=9)
        self.perf_ax_hist.set_title("Histograma de Trades", color=TEXT_PRI, fontsize=9)
        self.perf_fig.tight_layout(pad=1.5)
        self.perf_canvas = FigureCanvasTkAgg(self.perf_fig, master=self.perf_chart_frame)
        self.perf_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _criar_graficos_registro(self) -> None:
        self.reg_fig, self.reg_ax = plt.subplots(figsize=(12, 3))
        self.reg_fig.patch.set_facecolor(CARD_BG)
        self.reg_ax.set_facecolor(APP_BG)
        self.reg_ax.tick_params(colors=TEXT_SEC, labelsize=8)
        self.reg_ax.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)
        self.reg_ax.set_title("Lucro Acumulado por Dia", color=TEXT_PRI, fontsize=9)
        self.reg_fig.tight_layout(pad=1.5)
        self.reg_canvas = FigureCanvasTkAgg(self.reg_fig, master=self.reg_chart_frame)
        self.reg_canvas.get_tk_widget().pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    # REDESENHO DO GRÁFICO TRADING
    # ══════════════════════════════════════════════════════════════════════════
    def _redesenhar_grafico(self, preco: float) -> None:
        if preco <= 0:
            return
        self.prices.append(float(preco))
        if len(self.prices) > self.max_candles:
            self.prices = self.prices[-self.max_candles:]
        x = np.arange(len(self.prices))
        y = np.array(self.prices)
        self.price_line.set_data(x, y)

        if len(y) >= 9:
            ma9 = np.convolve(y, np.ones(9) / 9, mode="valid")
            self.ma_fast_line.set_data(x[-len(ma9):], ma9)
        else:
            self.ma_fast_line.set_data([], [])

        if len(y) >= 21:
            ma21 = np.convolve(y, np.ones(21) / 21, mode="valid")
            self.ma_slow_line.set_data(x[-len(ma21):], ma21)
        else:
            self.ma_slow_line.set_data([], [])

        if len(self.prices) > 1:
            self.ax.set_xlim(0, len(self.prices) - 1)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ══════════════════════════════════════════════════════════════════════════
    # ATUALIZAÇÃO DA TAB PERFORMANCE
    # ══════════════════════════════════════════════════════════════════════════
    def _update_performance_tab(self, snapshot: dict) -> None:
        win_rate        = float(snapshot.get("win_rate", 0.0))
        pf              = float(snapshot.get("profit_factor", 0.0))
        drawdown_max    = float(snapshot.get("drawdown_max_pct", 0.0))
        avg_gain        = float(snapshot.get("avg_gain", 0.0))
        avg_loss        = float(snapshot.get("avg_loss", 0.0))
        total_trades    = int(snapshot.get("total_trades", 0) or 0)
        lucro_liquido   = float(snapshot.get("lucro_liquido_brl", 0.0))
        sharpe          = float(snapshot.get("sharpe_simplificado", 0.0) if "sharpe_simplificado" in snapshot
                                else snapshot.get("sharpe", 0.0))
        expectancy      = float(snapshot.get("expectancy", 0.0))
        equity_history  = [float(v) for v in (snapshot.get("equity_history") or [])]
        bench_history   = [float(v) for v in (snapshot.get("benchmark_history") or [])]
        trades          = list(snapshot.get("trade_history") or [])
        near_logs       = list(snapshot.get("near_trade_logs") or [])
        confluence      = dict(snapshot.get("confluence") or {})
        total_cross     = int(snapshot.get("total_cross", 0) or 0)
        filtrados       = int(snapshot.get("cross_filtrados", 0) or 0)
        executados      = int(snapshot.get("cross_executados", 0) or 0)
        lucrativos      = int(snapshot.get("trades_lucrativos", 0) or 0)
        prejuizo        = int(snapshot.get("trades_prejuizo", 0) or 0)

        # KPIs
        cor_lucro = GREEN if lucro_liquido >= 0 else RED
        self.perf_total_trades.configure(text=str(total_trades))
        self.perf_win_rate.configure(text=f"{win_rate*100:.2f}%",
                                      text_color=GREEN if win_rate >= 0.5 else YELLOW)
        self.perf_lucro_liquido.configure(text=f"R$ {lucro_liquido:,.2f}", text_color=cor_lucro)
        self.perf_dd_max.configure(text=f"{drawdown_max:.2f}%",
                                    text_color=GREEN if drawdown_max < 5 else YELLOW if drawdown_max < 10 else RED)
        self.perf_pf.configure(text=f"{pf:.2f}",
                                text_color=GREEN if pf >= 1.3 else YELLOW if pf >= 1.0 else RED)
        self.perf_sharpe.configure(text=f"{sharpe:.2f}",
                                    text_color=GREEN if sharpe > 0 else RED)
        self.perf_expectancy.configure(text=f"R$ {expectancy:.4f}",
                                        text_color=GREEN if expectancy > 0 else RED)

        self.expectancy_text.configure(
            text=f"Avg Gain: R$ {avg_gain:.4f} | Avg Loss: R$ {avg_loss:.4f} | Expectância: R$ {expectancy:.4f}"
        )
        self.cross_stats_text.configure(
            text=f"Cross: {total_cross} | Filtrados: {filtrados} | Executados: {executados} | ✔ {lucrativos} | ✖ {prejuizo}"
        )

        # ── Gráfico equity + benchmark ─────────────────────────────────────────
        self.perf_ax_equity.cla()
        self.perf_ax_equity.set_facecolor(APP_BG)
        self.perf_ax_equity.tick_params(colors=TEXT_SEC, labelsize=8)
        self.perf_ax_equity.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)
        if equity_history:
            eq = np.array(equity_history)
            x  = np.arange(len(eq))
            self.perf_ax_equity.plot(x, eq, color=GREEN, linewidth=1.8, label="Equity")
            peak = np.maximum.accumulate(eq)
            self.perf_ax_equity.fill_between(x, eq, peak, where=peak >= eq,
                                              color=RED, alpha=0.12, label="Drawdown")
            if bench_history:
                bm = np.array(bench_history[:len(equity_history)])
                if len(bm) > 0 and bm[0] > 0 and equity_history[0] > 0:
                    bm_norm = (bm / bm[0]) * equity_history[0]
                    self.perf_ax_equity.plot(np.arange(len(bm_norm)), bm_norm,
                                              color=TEXT_SEC, linewidth=1.2,
                                              label="Benchmark BTC", linestyle="--")
        self.perf_ax_equity.legend(loc="upper left", fontsize=7, facecolor=CARD_BG,
                                    labelcolor=TEXT_PRI, framealpha=0.8)
        self.perf_ax_equity.set_title("Equity vs Benchmark", color=TEXT_PRI, fontsize=9)

        # ── Histograma de trades ───────────────────────────────────────────────
        profits = [float(t.get("lucro", 0.0)) for t in trades]
        self.perf_ax_hist.cla()
        self.perf_ax_hist.set_facecolor(APP_BG)
        self.perf_ax_hist.tick_params(colors=TEXT_SEC, labelsize=8)
        self.perf_ax_hist.grid(color=BORDER, alpha=0.25, linestyle="--", linewidth=0.5)
        if profits:
            colors_hist = [GREEN if p >= 0 else RED for p in profits]
            self.perf_ax_hist.hist(profits, bins=min(20, max(5, len(profits)//2)),
                                    color=BLUE, alpha=0.80, edgecolor=BORDER)
            self.perf_ax_hist.axvline(0, color=TEXT_SEC, linewidth=0.8, linestyle="--")
        self.perf_ax_hist.set_title("Histograma", color=TEXT_PRI, fontsize=9)
        self.perf_fig.tight_layout(pad=1.5)
        self.perf_canvas.draw_idle()

        # ── Deep logs ─────────────────────────────────────────────────────────
        self._fill_table_box(
            self.deep_logs_box,
            trades[-80:],
            "Data                | Tp | Entrada    | Saída      | Lucro      | Motivo",
            lambda r: (
                f"{str(r.get('data',''))[:19]:19} | "
                f"{str(r.get('tipo',''))[:2]:2} | "
                f"{float(r.get('entrada',0)):10.2f} | "
                f"{float(r.get('saida',0)):10.2f} | "
                f"{float(r.get('lucro',0)):+10.4f} | "
                f"{str(r.get('motivo',''))[:28]}"
            ),
        )

        # ── Quase-trades ──────────────────────────────────────────────────────
        self._fill_table_box(
            self.near_trades_box,
            near_logs[-100:],
            "Data                | BTC Preço  | Dist%    | Slope    | Motivo",
            lambda r: (
                f"{str(r.get('data',''))[:19]:19} | "
                f"{float(r.get('price_btc',0)):10.2f} | "
                f"{float(r.get('distancia_percentual',0))*100:8.5f} | "
                f"{float(r.get('slope',0)):8.4f} | "
                f"{str(r.get('reason',''))[:28]:28}"
            ),
        )

        # ── Confluência ───────────────────────────────────────────────────────
        self.confluence_rsi.configure(
            text=f"EMA9>EMA21: {'🟢' if confluence.get('ema_above_sma') else '🔴'}")
        self.confluence_dist.configure(
            text=f"Slope EMA9: {'🟢' if confluence.get('sma_slope_up') else '🔴'}")
        self.confluence_vol.configure(
            text=f"ATR Gate: {'🟢' if confluence.get('distancia_ok') else '🔴'}")
        self.confluence_bb.configure(
            text=f"Regime: {str(snapshot.get('strategy_mode_active','lateral')).upper()}")
        self.confluence_veredito.configure(
            text=str(confluence.get("veredito") or "Aguardando confluencia"),
            text_color=GREEN if "confirmada" in str(confluence.get("veredito","")) else YELLOW)

        self._update_registro_tab(snapshot)

    # ══════════════════════════════════════════════════════════════════════════
    # ATUALIZAÇÃO DO REGISTRO MENSAL
    # ══════════════════════════════════════════════════════════════════════════
    def _update_registro_tab(self, snapshot: dict) -> None:
        trades        = list(snapshot.get("trade_history") or [])
        monthly_profit = float(snapshot.get("monthly_profit", 0.0))
        best_day      = float(snapshot.get("best_day", 0.0))
        worst_day     = float(snapshot.get("worst_day", 0.0))
        sessions      = int(snapshot.get("sessions_count", 0) or 0)
        trades_db     = int(snapshot.get("trades_count_db", 0) or 0)
        total_trades  = int(snapshot.get("total_trades", 0) or 0)

        avg_trade = (monthly_profit / total_trades) if total_trades > 0 else 0.0

        cor_mes   = GREEN if monthly_profit >= 0 else RED
        cor_best  = GREEN
        cor_worst = RED

        self.reg_lucro_mes.configure(text=f"R$ {monthly_profit:,.2f}", text_color=cor_mes)
        self.reg_trades.configure(text=str(trades_db or total_trades))
        self.reg_sessoes.configure(text=str(sessions))
        self.reg_best.configure(text=f"R$ {best_day:,.4f}", text_color=cor_best)
        self.reg_worst.configure(text=f"R$ {worst_day:,.4f}", text_color=cor_worst)
        self.reg_avg_trade.configure(text=f"R$ {avg_trade:,.4f}",
                                      text_color=GREEN if avg_trade >= 0 else RED)

        # ── Tabela diária ──────────────────────────────────────────────────────
        by_day: dict[str, dict] = {}
        for t in trades:
            day = str(t.get("data", ""))[:10]
            if not day:
                continue
            row = by_day.setdefault(day, {"trades": 0, "lucro": 0.0, "wins": 0, "losses": 0})
            row["trades"] += 1
            pnl = float(t.get("lucro", 0.0))
            row["lucro"] += pnl
            if pnl >= 0:
                row["wins"] += 1
            else:
                row["losses"] += 1

        lines = ["Data       | Trades | Lucro Dia  | W | L | Win%  | Tendência"]
        lines.append("-" * 68)
        for day, vals in sorted(by_day.items(), reverse=True):
            wr = vals["wins"] / vals["trades"] * 100 if vals["trades"] > 0 else 0
            trend = "↑" if vals["lucro"] > 0 else "↓" if vals["lucro"] < 0 else "→"
            lines.append(
                f"{day:10} | {vals['trades']:6d} | {vals['lucro']:+10.4f} | "
                f"{vals['wins']:1d} | {vals['losses']:1d} | {wr:5.1f}% | {trend}"
            )
        self._set_textbox_content(self.reg_table, "\n".join(lines))

        # ── Detalhes de performance ───────────────────────────────────────────
        win_rate    = float(snapshot.get("win_rate", 0.0)) * 100
        pf          = float(snapshot.get("profit_factor", 0.0))
        dd_max      = float(snapshot.get("drawdown_max_pct", 0.0))
        avg_gain    = float(snapshot.get("avg_gain", 0.0))
        avg_loss    = float(snapshot.get("avg_loss", 0.0))
        expectancy  = float(snapshot.get("expectancy", 0.0))
        lucrativos  = int(snapshot.get("trades_lucrativos", 0) or 0)
        prejuizo_n  = int(snapshot.get("trades_prejuizo", 0) or 0)
        exposure    = float(snapshot.get("current_exposure_pct", 0.0))
        equity      = float(snapshot.get("equity_brl", 0.0))
        lucro_hoje  = float(snapshot.get("lucro_hoje_brl", 0.0))
        reserve     = float(snapshot.get("safe_reserve_brl", 0.0))

        det = [
            "══ PERFORMANCE GERAL ══════════════════",
            f"  Win Rate         : {win_rate:.2f}%",
            f"  Profit Factor    : {pf:.4f}",
            f"  Drawdown Máx     : {dd_max:.4f}%",
            f"  Trades Lucrativos: {lucrativos}",
            f"  Trades Prejuízo  : {prejuizo_n}",
            "",
            "══ MÉDIAS E EXPECTÂNCIA ═══════════════",
            f"  Avg Gain         : R$ {avg_gain:.4f}",
            f"  Avg Loss         : R$ {avg_loss:.4f}",
            f"  Expectância      : R$ {expectancy:.4f}",
            "",
            "══ SALDO E EXPOSIÇÃO ══════════════════",
            f"  Equity           : R$ {equity:.4f}",
            f"  Lucro Hoje       : R$ {lucro_hoje:+.4f}",
            f"  Reserva Segura   : R$ {reserve:.4f}",
            f"  Exposição Atual  : {exposure:.2f}%",
        ]
        self._set_textbox_content(self.reg_details, "\n".join(det))

        # ── Gráfico lucro acumulado ────────────────────────────────────────────
        self.reg_ax.cla()
        self.reg_ax.set_facecolor(APP_BG)
        self.reg_ax.tick_params(colors=TEXT_SEC, labelsize=8)
        self.reg_ax.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)

        if by_day:
            days   = sorted(by_day.keys())
            cum    = 0.0
            xs, ys = [], []
            for d in days:
                cum += by_day[d]["lucro"]
                xs.append(d[-5:])   # "MM-DD"
                ys.append(cum)

            colors_bar = [GREEN if v >= 0 else RED for v in ys]
            self.reg_ax.bar(range(len(ys)), ys, color=colors_bar, alpha=0.75, width=0.6)
            self.reg_ax.plot(range(len(ys)), ys, color=BLUE, linewidth=1.5, marker="o", markersize=4)
            self.reg_ax.axhline(0, color=TEXT_SEC, linewidth=0.8, linestyle="--")
            self.reg_ax.set_xticks(range(len(xs)))
            self.reg_ax.set_xticklabels(xs, rotation=45, ha="right", fontsize=8, color=TEXT_SEC)
            self.reg_ax.set_title("Lucro Acumulado por Dia", color=TEXT_PRI, fontsize=9)

        self.reg_fig.tight_layout(pad=1.5)
        self.reg_canvas.draw_idle()

    # ══════════════════════════════════════════════════════════════════════════
    # INDICADOR DE CONEXÃO
    # ══════════════════════════════════════════════════════════════════════════
    def _atualizar_indicador_conexao(self, preco: float) -> None:
        """Atualiza LED de conexão baseado em quantos ticks consecutivos sem dados."""
        if preco > 0:
            self._ticks_sem_dados = 0
            self._connection_state = "ok"
            self.conn_label.configure(text="● ONLINE", text_color=GREEN)
        else:
            self._ticks_sem_dados += 1
            if self._ticks_sem_dados >= _OFFLINE_ERROR_TICKS:
                self._connection_state = "error"
                self.conn_label.configure(text="● OFFLINE", text_color=RED)
            elif self._ticks_sem_dados >= _OFFLINE_WARN_TICKS:
                self._connection_state = "warn"
                self.conn_label.configure(text="● LENTO", text_color=YELLOW)

    # ══════════════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL com cache de snapshot
    # ══════════════════════════════════════════════════════════════════════════
    def loop_principal(self) -> None:
        self._flush_pending_logs()
        try:
            snapshot = self._obter_snapshot_com_timeout()
        except Exception as e:
            snapshot = self._last_valid_snapshot
            self.bridge.log_message(f"[WARN] Snapshot falhou: {e} — usando cache.")

        # Atualiza cache se snapshot válido
        preco_grafico = float(snapshot.get("price_usdt") or snapshot.get("price_brl") or 0.0)
        if preco_grafico > 0:
            with self._snapshot_lock:
                self._last_valid_snapshot = snapshot

        self._atualizar_indicador_conexao(preco_grafico)

        # Só redesenha se tiver preço (fallback usa cache)
        self._redesenhar_grafico(preco_grafico)
        self._update_performance_tab(snapshot)
        self.bridge.update_dashboard(snapshot)
        self.after(1000, self.loop_principal)

    def _obter_snapshot_com_timeout(self) -> dict:
        """Obtém snapshot com timeout para não travar a UI em lag de rede."""
        result: dict = {}
        exception: list = []

        def _fetch():
            try:
                result.update(self.controller.get_runtime_snapshot())
            except Exception as e:
                exception.append(e)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=_SNAPSHOT_TIMEOUT_SEC)

        if exception:
            raise exception[0]
        if not result:
            raise TimeoutError("Snapshot demorou demais (rede lenta?)")
        return result

    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS DE TEXTBOX
    # ══════════════════════════════════════════════════════════════════════════
    def _fill_table_box(self, box: ctk.CTkTextbox, rows: list[dict],
                         header: str, formatter) -> None:
        lines = [header, "─" * len(header)]
        lines.extend(formatter(row) for row in rows)
        self._set_textbox_content(box, "\n".join(lines))

    def _set_textbox_content(self, box: ctk.CTkTextbox, content: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", content)
        box.see("end")
        box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # HANDLERS DE BOTÕES E CONTROLES
    # ══════════════════════════════════════════════════════════════════════════
    def _on_start_clicked(self) -> None:
        ok, msg = self.controller.start()
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
            self.bridge.log_message(f"Relatório gerado: {path_or_err}")
        else:
            self.bridge.log_message(f"Falha ao gerar relatório: {path_or_err}")

    def _on_profile_change(self, profile: str) -> None:
        self.controller.apply_profile(profile)

    def _on_accumulation_toggle(self) -> None:
        self.controller.set_accumulation_mode(self.accumulate_switch.get() == 1)

    def _abrir_janela_simulacao(self) -> None:
        if hasattr(self, "_cfg_window") and self._cfg_window is not None:
            try:
                if self._cfg_window.winfo_exists():
                    self._cfg_window.focus()
                    return
            except Exception:
                pass
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
        self.bridge.log_message("Configuração atualizada.")

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
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
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

    def shutdown(self) -> None:
        """Alias para compatibilidade com chamadas externas."""
        self._on_close()


# Alias para compatibilidade com imports existentes
MainWindow = TradingApp