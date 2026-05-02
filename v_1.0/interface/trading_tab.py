"""
trading_tab.py — Interface de trading reformulada v3.

Melhorias:
  - Resiliência de conexão: cache do último snapshot válido
  - Indicador de lag de rede no cabeçalho
  - Blocos de análise alimentados por dados reais do snapshot
  - Gráfico com EMA9, EMA21 e EMA38 reais (do engine, não convolução local)
  - Bloco de "Timing do Trade" com tempo desde último trade
  - Todos os 8 blocos funcionais e conectados
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

APP_BG    = "#0d1117"
CARD_BG   = "#161b22"
CARD_BG2  = "#1c2128"
BORDER    = "#30363d"
GREEN     = "#22c55e"
RED       = "#ef4444"
YELLOW    = "#f59e0b"
BLUE      = "#38bdf8"
PURPLE    = "#a78bfa"
TEXT_PRI  = "#e6edf3"
TEXT_SEC  = "#8b949e"
ACCENT    = "#1f6feb"

_OFFLINE_WARN  = 3
_OFFLINE_ERROR = 8


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _mix(a: str, b: str, f: float) -> str:
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    f = max(0.0, min(1.0, f))
    return _rgb_to_hex((int(ra*f + rb*(1-f)), int(ga*f + gb*(1-f)), int(ba*f + bb*(1-f))))


def _card(parent, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10,
                        border_width=1, border_color=BORDER)
    if title:
        ctk.CTkLabel(card, text=title, font=("JetBrains Mono", 9, "bold"),
                     text_color=TEXT_SEC).pack(anchor="w", padx=10, pady=(8, 2))
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    return card, body


def _row_label(parent, title: str, width: int = 80) -> ctk.CTkLabel:
    """Cria linha key-value e retorna o label do valor."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=1)
    ctk.CTkLabel(row, text=title, font=("JetBrains Mono", 10),
                 text_color=TEXT_SEC, width=width, anchor="w").pack(side="left")
    lbl = ctk.CTkLabel(row, text="--", font=("JetBrains Mono", 10), text_color=TEXT_PRI)
    lbl.pack(side="right")
    return lbl


class TradingTab(ctk.CTkFrame):
    def __init__(self, master, market_data, trade_manager,
                 bot_controller=None,
                 on_trade_update: Callable[[], None] | None = None):
        super().__init__(master, fg_color=APP_BG)
        self.logger          = logging.getLogger(__name__)
        self.market_data     = market_data
        self.trade_manager   = trade_manager
        self.bot_controller  = bot_controller
        self.on_trade_update = on_trade_update

        self.bot_running      = False
        self.preco_anterior: float | None = None
        self.modo_operacao    = "desligado"

        self._ultimo_preco_usdt: float = 0.0
        self._ultimo_preco_brl:  float = 0.0
        self._preco_color_atual  = TEXT_PRI
        self._preco_anim_id: str | None = None
        self._pulse_id:      str | None = None

        self._snapshot: dict[str, Any] = {}
        self._last_valid_snap: dict[str, Any] = {}
        self._ticks_sem_dados: int = 0
        self._last_trade_ts: float = 0.0

        self.max_candles = 180
        self.prices: list[float] = []
        # Histórico de EMAs do engine (real, não convolução)
        self._ema9_hist:  list[float] = []
        self._ema21_hist: list[float] = []
        self._ema38_hist: list[float] = []

        self._build_layout()
        self._build_chart()
        self._update_status_footer()
        self._loop_atualizar()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════
    def _build_layout(self) -> None:
        # ── Cabeçalho ─────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                           border_width=1, border_color=BORDER)
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=16, pady=10)

        self.preco_label = ctk.CTkLabel(left, text="BTC/USDT: --",
                                         font=("JetBrains Mono", 20, "bold"), text_color=TEXT_PRI)
        self.preco_label.pack(anchor="w")

        sig_row = ctk.CTkFrame(left, fg_color="transparent")
        sig_row.pack(anchor="w", pady=(4, 0))
        self.buy_indicator  = ctk.CTkLabel(sig_row, text="●", font=("Segoe UI", 14, "bold"), text_color=BORDER)
        self.buy_indicator.pack(side="left")
        ctk.CTkLabel(sig_row, text="Compra", font=("JetBrains Mono", 10), text_color=TEXT_SEC).pack(side="left", padx=(3,10))
        self.sell_indicator = ctk.CTkLabel(sig_row, text="●", font=("Segoe UI", 14, "bold"), text_color=BORDER)
        self.sell_indicator.pack(side="left")
        ctk.CTkLabel(sig_row, text="Venda", font=("JetBrains Mono", 10), text_color=TEXT_SEC).pack(side="left", padx=(3,10))
        self.conn_dot = ctk.CTkLabel(sig_row, text="● ONLINE",
                                      font=("JetBrains Mono", 10, "bold"), text_color=GREEN)
        self.conn_dot.pack(side="left", padx=(6, 0))

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=16, pady=10)
        self.saldo_label = ctk.CTkLabel(right, text="Saldo: --",
                                         font=("JetBrains Mono", 12), text_color=TEXT_PRI)
        self.saldo_label.pack(anchor="e")
        self.lucro_label = ctk.CTkLabel(right, text="Lucro: R$0.00",
                                         font=("JetBrains Mono", 13, "bold"), text_color=GREEN)
        self.lucro_label.pack(anchor="e", pady=(4, 0))
        self.drawdown_label = ctk.CTkLabel(right, text="Drawdown: 0.00%",
                                            font=("JetBrains Mono", 11), text_color=GREEN)
        self.drawdown_label.pack(anchor="e", pady=(2, 0))

        # ── Alerta inteligente ────────────────────────────────────────────────
        self.alert_frame = ctk.CTkFrame(self, fg_color=CARD_BG2, corner_radius=8,
                                         border_width=1, border_color=BORDER)
        self.alert_frame.pack(fill="x", padx=16, pady=(0, 6))
        self.alert_label = ctk.CTkLabel(self.alert_frame,
                                         text="⏳  Aguardando dados do mercado...",
                                         font=("JetBrains Mono", 11), text_color=TEXT_SEC)
        self.alert_label.pack(padx=12, pady=7, anchor="w")

        # ── Corpo ─────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=APP_BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        # Coluna esquerda
        left_col = ctk.CTkFrame(body, fg_color=APP_BG)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_col.grid_rowconfigure(0, weight=3)
        left_col.grid_rowconfigure(1, weight=2)
        left_col.grid_columnconfigure(0, weight=1)

        self.chart_frame = ctk.CTkFrame(left_col, fg_color=CARD_BG, corner_radius=14,
                                         border_width=1, border_color=BORDER)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        analysis = ctk.CTkFrame(left_col, fg_color=APP_BG)
        analysis.grid(row=1, column=0, sticky="nsew")
        analysis.grid_columnconfigure((0, 1, 2), weight=1)

        self._build_market_status(analysis, col=0)
        self._build_ema_block(analysis, col=1)
        self._build_decision_block(analysis, col=2)

        # Coluna direita
        right_col = ctk.CTkScrollableFrame(body, fg_color=APP_BG, corner_radius=0)
        right_col.grid(row=0, column=1, sticky="nsew")

        self._build_controls(right_col)
        self._build_filters_block(right_col)
        self._build_sizing_block(right_col)
        self._build_performance_block(right_col)
        self._build_last_trade_block(right_col)
        self._build_timing_block(right_col)

        # ── Rodapé ────────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8,
                              border_width=1, border_color=BORDER)
        footer.pack(fill="x", padx=16, pady=(0, 10))
        self.status_label = ctk.CTkLabel(footer, text="PARADO: DESLIGADO",
                                          font=("JetBrains Mono", 11), text_color=TEXT_PRI)
        self.status_label.pack(padx=12, pady=6, anchor="w")

    # ── Bloco 1: Status do Mercado ─────────────────────────────────────────────
    def _build_market_status(self, parent, col: int) -> None:
        card, body = _card(parent, "STATUS DO MERCADO")
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 4))
        self.regime_icon  = ctk.CTkLabel(body, text="⏳", font=("Segoe UI", 20))
        self.regime_icon.pack(pady=(2, 0))
        self.regime_label = ctk.CTkLabel(body, text="AGUARDANDO",
                                          font=("JetBrains Mono", 11, "bold"), text_color=TEXT_SEC)
        self.regime_label.pack()
        self.tendencia_label = ctk.CTkLabel(body, text="Força: --",
                                             font=("JetBrains Mono", 10), text_color=TEXT_SEC)
        self.tendencia_label.pack(pady=(2, 0))
        ctk.CTkFrame(body, fg_color=BORDER, height=1).pack(fill="x", pady=5)
        self.dist_lbl    = _row_label(body, "DIST EMA9-21", 80)
        self.slope38_lbl = _row_label(body, "SLOPE EMA38",  80)
        self.buffer_lbl  = _row_label(body, "BUFFER",       80)

    # ── Bloco 2: Estrutura das EMAs ───────────────────────────────────────────
    def _build_ema_block(self, parent, col: int) -> None:
        card, body = _card(parent, "ESTRUTURA DAS EMAs")
        card.grid(row=0, column=col, sticky="nsew", padx=(2, 2))
        self.align_icon  = ctk.CTkLabel(body, text="◈", font=("Segoe UI", 18))
        self.align_icon.pack(pady=(2, 0))
        self.align_label = ctk.CTkLabel(body, text="--",
                                         font=("JetBrains Mono", 10, "bold"), text_color=TEXT_SEC)
        self.align_label.pack()
        ctk.CTkFrame(body, fg_color=BORDER, height=1).pack(fill="x", pady=5)
        self.ema9_val  = _row_label(body, "EMA 9",  50)
        self.ema21_val = _row_label(body, "EMA 21", 50)
        self.ema38_val = _row_label(body, "EMA 38", 50)
        ctk.CTkFrame(body, fg_color=BORDER, height=1).pack(fill="x", pady=5)
        self.cascade_label = ctk.CTkLabel(body, text="Cascata: --",
                                           font=("JetBrains Mono", 10), text_color=TEXT_SEC)
        self.cascade_label.pack()

    # ── Bloco 3: Decisão do Bot ───────────────────────────────────────────────
    def _build_decision_block(self, parent, col: int) -> None:
        card, body = _card(parent, "DECISÃO DO BOT")
        card.grid(row=0, column=col, sticky="nsew", padx=(4, 0))
        self.decision_icon   = ctk.CTkLabel(body, text="🤔", font=("Segoe UI", 20))
        self.decision_icon.pack(pady=(2, 0))
        self.decision_action = ctk.CTkLabel(body, text="AGUARDANDO",
                                             font=("JetBrains Mono", 11, "bold"), text_color=TEXT_SEC)
        self.decision_action.pack()
        ctk.CTkFrame(body, fg_color=BORDER, height=1).pack(fill="x", pady=5)
        ctk.CTkLabel(body, text="MOTIVO", font=("JetBrains Mono", 9), text_color=TEXT_SEC).pack(anchor="w")
        self.decision_reason = ctk.CTkLabel(body, text="--", font=("JetBrains Mono", 10),
                                             text_color=TEXT_PRI, wraplength=150, justify="left")
        self.decision_reason.pack(anchor="w", pady=(1, 5))
        ctk.CTkLabel(body, text="CONFIANÇA", font=("JetBrains Mono", 9), text_color=TEXT_SEC).pack(anchor="w")
        self.confidence_bar = ctk.CTkProgressBar(body, height=10, corner_radius=5,
                                                  fg_color=BORDER, progress_color=GREEN)
        self.confidence_bar.pack(fill="x", pady=(2, 0))
        self.confidence_bar.set(0)
        self.confidence_pct = ctk.CTkLabel(body, text="0%",
                                            font=("JetBrains Mono", 9), text_color=TEXT_SEC)
        self.confidence_pct.pack(anchor="e")

    # ── Controles ─────────────────────────────────────────────────────────────
    def _build_controls(self, parent) -> None:
        ctrl = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12,
                            border_width=1, border_color=BORDER)
        ctrl.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(ctrl, text="CONTROLES", font=("JetBrains Mono", 11, "bold"),
                     text_color=TEXT_PRI).pack(pady=(10, 6))

        self.real_mode_switch = ctk.CTkSwitch(ctrl, text="Modo Real",
                                               font=("JetBrains Mono", 11), progress_color=ACCENT,
                                               command=self._alternar_modo_real)
        self.real_mode_switch.pack(pady=(0, 3))
        self.simulacao_mode_switch = ctk.CTkSwitch(ctrl, text="Modo Simulação",
                                                    font=("JetBrains Mono", 11), progress_color=ACCENT,
                                                    command=self._alternar_modo_simulacao)
        self.simulacao_mode_switch.pack(pady=(0, 8))

        self.simulacao_button = ctk.CTkButton(ctrl, text="⚙ Configurar Simulação", height=32,
                                               font=("JetBrains Mono", 10),
                                               fg_color=CARD_BG2, hover_color=BORDER,
                                               command=self._abrir_modal_simulacao)
        self.simulacao_button.pack(pady=(0, 4), padx=14, fill="x")

        self.bot_button = ctk.CTkButton(ctrl, text="▶  INICIAR BOT", height=38,
                                         font=("JetBrains Mono", 12, "bold"),
                                         fg_color="#166534", hover_color="#15803d",
                                         command=self._toggle_execucao)
        self.bot_button.pack(pady=(0, 12), padx=14, fill="x")

    # ── Bloco 4: Filtros ──────────────────────────────────────────────────────
    def _build_filters_block(self, parent) -> None:
        card, body = _card(parent, "FILTROS DE ENTRADA")
        card.pack(fill="x", pady=(0, 6))
        self._filter_labels: dict[str, ctk.CTkLabel] = {}
        filtros = [
            ("cascade", "EMA cascata (9>21>38)"),
            ("slope",   "Slope EMA9 positivo"),
            ("dist",    "Distância mínima ok"),
            ("slope38", "Slope EMA38 positivo"),
            ("atr",     "ATR gate ok"),
        ]
        for key, text in filtros:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            icon = ctk.CTkLabel(row, text="◌", font=("Segoe UI", 12, "bold"),
                                text_color=BORDER, width=18)
            icon.pack(side="left")
            ctk.CTkLabel(row, text=text, font=("JetBrains Mono", 10),
                         text_color=TEXT_SEC).pack(side="left", padx=(4, 0))
            self._filter_labels[key] = icon

    # ── Bloco 5: Position Sizing ───────────────────────────────────────────────
    def _build_sizing_block(self, parent) -> None:
        card, body = _card(parent, "POSITION SIZING")
        card.pack(fill="x", pady=(0, 6))
        self._sz: dict[str, ctk.CTkLabel] = {}
        for key, text in [("saldo","Saldo"), ("risco","Risco"), ("valor","Trade"), ("tipo","Tipo")]:
            self._sz[key] = _row_label(body, text, 60)

    # ── Bloco 6: Performance ──────────────────────────────────────────────────
    def _build_performance_block(self, parent) -> None:
        card, body = _card(parent, "PERFORMANCE")
        card.pack(fill="x", pady=(0, 6))
        self._perf: dict[str, ctk.CTkLabel] = {}
        for key, text in [("trades","Trades"), ("winrate","Win rate"),
                           ("pnl","PnL"), ("drawdown","Drawdown"), ("modo","Modo"), ("pf","Profit Factor")]:
            self._perf[key] = _row_label(body, text, 80)

    # ── Bloco 7: Último Trade ─────────────────────────────────────────────────
    def _build_last_trade_block(self, parent) -> None:
        card, body = _card(parent, "ÚLTIMO TRADE")
        card.pack(fill="x", pady=(0, 6))
        self._lt: dict[str, ctk.CTkLabel] = {}
        for key, text in [("tipo","Tipo"), ("entrada","Entrada"), ("saida","Saída"),
                           ("pnl","PnL"), ("motivo","Motivo"), ("tempo","Duração")]:
            self._lt[key] = _row_label(body, text, 60)

    # ── Bloco 8: Timing do Trade ──────────────────────────────────────────────
    def _build_timing_block(self, parent) -> None:
        card, body = _card(parent, "TIMING")
        card.pack(fill="x", pady=(0, 6))
        self._tm: dict[str, ctk.CTkLabel] = {}
        for key, text in [("desde_trade","Desde último trade"), ("overtrading","Overtrading"),
                           ("pausa","Próx. permitido"), ("cross","Total cross")]:
            self._tm[key] = _row_label(body, text, 100)

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO
    # ══════════════════════════════════════════════════════════════════════════
    def _build_chart(self) -> None:
        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_facecolor(APP_BG)
        self.price_line, = self.ax.plot([], [], color=TEXT_PRI, linewidth=1.8, label="BTC")
        self.ema9_line,  = self.ax.plot([], [], color=GREEN,    linewidth=1.2, label="EMA9")
        self.ema21_line, = self.ax.plot([], [], color=RED,      linewidth=1.2, label="EMA21")
        self.ema38_line, = self.ax.plot([], [], color=YELLOW,   linewidth=1.2, label="EMA38", linestyle="--")
        self.ax.tick_params(colors=TEXT_SEC, labelsize=8)
        self.ax.grid(color=BORDER, alpha=0.35, linestyle="--", linewidth=0.5)
        self.ax.legend(loc="upper left", fontsize=7, facecolor=CARD_BG,
                       labelcolor=TEXT_PRI, framealpha=0.7)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

    # ══════════════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL
    # ══════════════════════════════════════════════════════════════════════════
    def _loop_atualizar(self) -> None:
        try:
            self._coletar_precos()
            self._atualizar_snapshot()
            self._atualizar_indicador_conexao()
            self._atualizar_grafico_linhas()
            self._atualizar_todos_blocos()
        except Exception as e:
            self.logger.exception("Erro no loop: %s", e)
        self.after(1000, self._loop_atualizar)

    def _coletar_precos(self) -> None:
        usdt, brl = 0.0, 0.0
        try:
            usdt = float(self.market_data.pegar_preco_atual("BTCUSDT") or 0.0)
        except Exception:
            pass
        try:
            brl = float(self.market_data.pegar_preco_atual("BTCBRL") or 0.0)
        except Exception:
            try:
                ubrl = float(self.market_data.pegar_preco_atual("USDTBRL") or 0.0)
                brl = usdt * ubrl if ubrl > 0 else usdt
            except Exception:
                brl = usdt

        if usdt > 0:
            self._atualizar_preco_animado(usdt)
            self._ultimo_preco_usdt = usdt
        if brl > 0:
            self._ultimo_preco_brl = brl
        if usdt > 0:
            self.prices.append(usdt)
            if len(self.prices) > self.max_candles:
                self.prices = self.prices[-self.max_candles:]

    def _atualizar_snapshot(self) -> None:
        if self.bot_controller is not None:
            try:
                snap = self.bot_controller.get_runtime_snapshot() or {}
                if snap:
                    self._snapshot = snap
                    self._last_valid_snap = snap
            except Exception:
                # Fallback: usa último snapshot válido
                self._snapshot = self._last_valid_snap
        else:
            self._snapshot = {}

    def _atualizar_indicador_conexao(self) -> None:
        preco = self._ultimo_preco_usdt
        if preco > 0:
            self._ticks_sem_dados = 0
            self.conn_dot.configure(text="● ONLINE", text_color=GREEN)
        else:
            self._ticks_sem_dados += 1
            if self._ticks_sem_dados >= _OFFLINE_ERROR:
                self.conn_dot.configure(text="● OFFLINE", text_color=RED)
            elif self._ticks_sem_dados >= _OFFLINE_WARN:
                self.conn_dot.configure(text="● LENTO",   text_color=YELLOW)

    def _atualizar_grafico_linhas(self) -> None:
        if not self.prices:
            return

        # Usa EMAs reais do engine quando disponíveis
        snap = self._snapshot
        ctx  = snap.get("last_signal_context") or {}
        dbg  = snap.get("strategy_debug") or {}

        e9  = float(ctx.get("ema9")  or dbg.get("ema9")  or 0.0)
        e21 = float(ctx.get("ema21") or dbg.get("ema21") or 0.0)
        e38 = float(ctx.get("ema38") or dbg.get("ema38") or 0.0)

        if e9 > 0:
            self._ema9_hist.append(e9)
        if e21 > 0:
            self._ema21_hist.append(e21)
        if e38 > 0:
            self._ema38_hist.append(e38)
        # Limita histórico
        n = self.max_candles
        self._ema9_hist  = self._ema9_hist[-n:]
        self._ema21_hist = self._ema21_hist[-n:]
        self._ema38_hist = self._ema38_hist[-n:]

        x = np.arange(len(self.prices))
        y = np.array(self.prices)
        self.price_line.set_data(x, y)

        # EMA9 — do engine se disponível, senão convolução local
        if len(self._ema9_hist) >= 2:
            xe = np.arange(len(x) - len(self._ema9_hist), len(x))
            self.ema9_line.set_data(xe[-len(self._ema9_hist):], self._ema9_hist)
        elif len(y) >= 9:
            m = np.convolve(y, np.ones(9)/9, mode="valid")
            self.ema9_line.set_data(x[-len(m):], m)
        else:
            self.ema9_line.set_data([], [])

        # EMA21
        if len(self._ema21_hist) >= 2:
            xe = np.arange(len(x) - len(self._ema21_hist), len(x))
            self.ema21_line.set_data(xe[-len(self._ema21_hist):], self._ema21_hist)
        elif len(y) >= 21:
            m = np.convolve(y, np.ones(21)/21, mode="valid")
            self.ema21_line.set_data(x[-len(m):], m)
        else:
            self.ema21_line.set_data([], [])

        # EMA38
        if len(self._ema38_hist) >= 2:
            xe = np.arange(len(x) - len(self._ema38_hist), len(x))
            self.ema38_line.set_data(xe[-len(self._ema38_hist):], self._ema38_hist)
        elif len(y) >= 38:
            m = np.convolve(y, np.ones(38)/38, mode="valid")
            self.ema38_line.set_data(x[-len(m):], m)
        else:
            self.ema38_line.set_data([], [])

        if len(self.prices) > 2:
            self.ax.set_xlim(max(0, len(self.prices) - self.max_candles), len(self.prices))
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ══════════════════════════════════════════════════════════════════════════
    # ATUALIZAÇÃO DOS BLOCOS
    # ══════════════════════════════════════════════════════════════════════════
    def _atualizar_todos_blocos(self) -> None:
        snap = self._snapshot
        dbg  = snap.get("strategy_debug") or {}
        ctx  = snap.get("last_signal_context") or {}

        self._update_header(snap)
        self._update_market_status(snap, dbg, ctx)
        self._update_ema_block(dbg, ctx)
        self._update_decision_block(snap, ctx)
        self._update_filters(dbg, ctx)
        self._update_sizing(snap)
        self._update_performance(snap)
        self._update_last_trade(snap)
        self._update_timing(snap, ctx)
        self._update_alert(snap, dbg)

    def _update_header(self, snap: dict) -> None:
        equity = float(snap.get("equity_brl") or 0.0)
        lucro  = float(snap.get("lucro_hoje_brl") or 0.0)
        dd     = float(snap.get("current_drawdown_pct") or 0.0)
        if equity > 0:
            self.saldo_label.configure(text=f"Saldo: R$ {equity:,.2f}")
        cor_l = GREEN if lucro >= 0 else RED
        s = "+" if lucro >= 0 else ""
        self.lucro_label.configure(text=f"Lucro: {s}R$ {lucro:,.4f}", text_color=cor_l)
        cor_dd = GREEN if dd < 5 else YELLOW if dd < 10 else RED
        self.drawdown_label.configure(text=f"Drawdown: {dd:.2f}%", text_color=cor_dd)

    def _update_market_status(self, snap: dict, dbg: dict, ctx: dict) -> None:
        regime   = str(dbg.get("regime") or snap.get("strategy_mode_active") or "lateral").lower()
        warming  = bool(ctx.get("warming_up", False))
        buf      = int(ctx.get("buffer_len") or dbg.get("buffer_len") or 0)
        req      = int(ctx.get("required_periods") or 38)
        dist_pct = float(ctx.get("distancia_percentual") or dbg.get("dist_pct") or 0.0)
        slope38  = float(ctx.get("slope_ema38") or dbg.get("slope38") or 0.0)

        if warming:
            self.regime_icon.configure(text="⏳")
            self.regime_label.configure(text=f"AQUECENDO {buf}/{req}", text_color=TEXT_SEC)
            self.tendencia_label.configure(text="Força: --", text_color=TEXT_SEC)
        elif "forte" in regime:
            self.regime_icon.configure(text="🟢")
            self.regime_label.configure(text="TENDÊNCIA FORTE", text_color=GREEN)
            self.tendencia_label.configure(text="Força: ALTA", text_color=GREEN)
        elif "fraca" in regime:
            self.regime_icon.configure(text="🟡")
            self.regime_label.configure(text="TENDÊNCIA FRACA", text_color=YELLOW)
            self.tendencia_label.configure(text="Força: MÉDIA", text_color=YELLOW)
        elif "lateral" in regime:
            self.regime_icon.configure(text="🟡")
            self.regime_label.configure(text="LATERAL", text_color=YELLOW)
            self.tendencia_label.configure(text="Força: FRACA", text_color=YELLOW)
        else:
            self.regime_icon.configure(text="🔴")
            self.regime_label.configure(text="INDEFINIDO", text_color=RED)
            self.tendencia_label.configure(text="Força: --", text_color=TEXT_SEC)

        cor_d = GREEN if dist_pct >= 0.0005 else YELLOW if dist_pct >= 0.0003 else RED
        self.dist_lbl.configure(text=f"{dist_pct*100:.5f}%", text_color=cor_d)
        cor_s38 = GREEN if slope38 > 0 else RED
        self.slope38_lbl.configure(text=f"{slope38:+.3f}", text_color=cor_s38)
        self.buffer_lbl.configure(text=f"{buf}/{req}")

    def _update_ema_block(self, dbg: dict, ctx: dict) -> None:
        e9  = float(ctx.get("ema9")  or dbg.get("ema9")  or 0.0)
        e21 = float(ctx.get("ema21") or dbg.get("ema21") or 0.0)
        e38 = float(ctx.get("ema38") or dbg.get("ema38") or 0.0)
        cbull = bool(ctx.get("cascade_bull") or dbg.get("cascade_bull") or False)
        cbear = bool(ctx.get("cascade_bear") or dbg.get("cascade_bear") or False)

        def _fmt(v, ref):
            if v <= 0: return "--", TEXT_SEC
            return f"{v:,.2f}", (GREEN if v > ref else RED if v < ref else TEXT_PRI)

        if e21 > 0:
            t9,  c9  = _fmt(e9, e21)
            t38, c38 = _fmt(e38, e21)
            self.ema9_val.configure(text=t9,           text_color=c9)
            self.ema21_val.configure(text=f"{e21:,.2f}", text_color=TEXT_PRI)
            self.ema38_val.configure(text=t38,          text_color=c38)
        else:
            for lbl in (self.ema9_val, self.ema21_val, self.ema38_val):
                lbl.configure(text="--", text_color=TEXT_SEC)

        if cbull:
            self.align_icon.configure(text="🟢")
            self.align_label.configure(text="ALTA 9>21>38", text_color=GREEN)
            self.cascade_label.configure(text="Cascata: ✔ confirmada", text_color=GREEN)
        elif cbear:
            self.align_icon.configure(text="🔴")
            self.align_label.configure(text="BAIXA 9<21<38", text_color=RED)
            self.cascade_label.configure(text="Cascata: ✔ baixa", text_color=RED)
        else:
            self.align_icon.configure(text="🟡")
            self.align_label.configure(text="SEM ALINHAMENTO", text_color=YELLOW)
            self.cascade_label.configure(text="Cascata: ✖ não confirmada", text_color=YELLOW)

    def _update_decision_block(self, snap: dict, ctx: dict) -> None:
        signal   = str(ctx.get("signal") or "none").lower()
        reason   = str(ctx.get("reason") or snap.get("strategy_mode_active") or "--")
        strength = float(ctx.get("signal_strength") or snap.get("signal_strength") or 0.0)
        position = bool(snap.get("position_open", False))

        if position:
            self.decision_icon.configure(text="💼")
            self.decision_action.configure(text="EM POSIÇÃO", text_color=BLUE)
        elif signal == "buy":
            self.decision_icon.configure(text="🟢")
            self.decision_action.configure(text="COMPRAR", text_color=GREEN)
        elif signal == "sell":
            self.decision_icon.configure(text="🔴")
            self.decision_action.configure(text="VENDER", text_color=RED)
        else:
            self.decision_icon.configure(text="⏸")
            self.decision_action.configure(text="NÃO OPERAR", text_color=YELLOW)

        reason_map = {
            "mercado_lateral_bloqueado":        "EMA colada (lateral)",
            "mercado_lateral_sem_operacao":     "Lateral — aguardando",
            "cascata_nao_alinhada":             "EMAs fora de cascata",
            "dist_insuficiente":                "Distância insuficiente",
            "slope_negativo":                   "Slope EMA9 negativo",
            "atr_gate_nao_atingido":            "Volatilidade baixa",
            "posicao_mantida":                  "Posição aberta",
            "crossover_alta_cascata_confirmado":"Crossover + cascata ✔",
            "tendencia_cascata_agressiva":      "Tendência forte 🔥",
            "cascata_ok_aguardando_crossover":  "Aguardando crossover",
            "dados_insuficientes":              "Aquecendo...",
        }
        show = reason
        for k, v in reason_map.items():
            if k in reason:
                show = v
                break
        self.decision_reason.configure(text=show)

        cor_bar = GREEN if strength >= 0.7 else YELLOW if strength >= 0.4 else RED
        self.confidence_bar.set(strength)
        self.confidence_bar.configure(progress_color=cor_bar)
        self.confidence_pct.configure(text=f"{int(strength*100)}%", text_color=cor_bar)

    def _update_filters(self, dbg: dict, ctx: dict) -> None:
        cbull   = bool(ctx.get("cascade_bull") or dbg.get("cascade_bull") or False)
        slope9  = float(ctx.get("slope_ema9")  or dbg.get("slope9")  or 0.0)
        slope38 = float(ctx.get("slope_ema38") or dbg.get("slope38") or 0.0)
        dist    = float(ctx.get("distancia_percentual") or dbg.get("dist_pct") or 0.0)
        atr     = float(ctx.get("atr")      or dbg.get("atr")  or 0.0)
        gate    = float(ctx.get("atr_gate") or 0.0)
        e9      = float(ctx.get("ema9")  or dbg.get("ema9")  or 0.0)
        e21     = float(ctx.get("ema21") or dbg.get("ema21") or 0.0)
        dist_abs = abs(e9 - e21)

        checks = {
            "cascade": cbull,
            "slope":   slope9 > 0,
            "dist":    dist >= 0.0005,
            "slope38": slope38 > 0,
            "atr":     (gate <= 0) or (atr <= 0) or (dist_abs >= gate),
        }
        for key, ok in checks.items():
            lbl = self._filter_labels.get(key)
            if lbl:
                lbl.configure(text="✔" if ok else "✖", text_color=GREEN if ok else RED)

    def _update_sizing(self, snap: dict) -> None:
        equity   = float(snap.get("equity_brl")           or 0.0)
        exposure = float(snap.get("current_exposure_brl") or 0.0)
        exp_pct  = float(snap.get("current_exposure_pct") or 0.0)
        strength = float(snap.get("signal_strength") or
                         (snap.get("last_signal_context") or {}).get("signal_strength") or 0.0)

        if strength >= 0.7:
            tipo, cor = "AGRESSIVO 🔥", GREEN
        elif strength >= 0.4:
            tipo, cor = "NORMAL", BLUE
        else:
            tipo, cor = "REDUZIDO", YELLOW

        self._sz["saldo"].configure(text=f"R$ {equity:,.2f}")
        self._sz["risco"].configure(text=f"{exp_pct:.1f}%")
        self._sz["valor"].configure(text=f"R$ {exposure:,.2f}")
        self._sz["tipo"].configure(text=tipo, text_color=cor)

    def _update_performance(self, snap: dict) -> None:
        trades  = int((snap.get("trades_lucrativos") or 0)) + int((snap.get("trades_prejuizo") or 0))
        wr      = float(snap.get("win_rate") or 0.0) * 100
        pnl     = float(snap.get("lucro_hoje_brl") or 0.0)
        dd      = float(snap.get("current_drawdown_pct") or 0.0)
        modo    = str(snap.get("strategy_mode_active") or "--").upper()
        pf      = float(snap.get("profit_factor") or 0.0)

        cor_pnl = GREEN if pnl >= 0 else RED
        s = "+" if pnl >= 0 else ""

        self._perf["trades"].configure(text=str(trades))
        self._perf["winrate"].configure(text=f"{wr:.1f}%",
                                         text_color=GREEN if wr >= 50 else YELLOW)
        self._perf["pnl"].configure(text=f"{s}R$ {pnl:.4f}", text_color=cor_pnl)
        self._perf["drawdown"].configure(text=f"{dd:.2f}%",
                                          text_color=GREEN if dd < 5 else YELLOW if dd < 10 else RED)
        self._perf["modo"].configure(text=modo)
        self._perf["pf"].configure(text=f"{pf:.2f}",
                                    text_color=GREEN if pf >= 1.3 else YELLOW if pf >= 1.0 else RED)

    def _update_last_trade(self, snap: dict) -> None:
        lt = snap.get("last_trade")
        if not lt:
            return
        side    = str(lt.get("side") or "--")
        price   = float(lt.get("price") or 0.0)
        pnl     = float(lt.get("pnl_brl") or 0.0)
        pnl_pct = float(lt.get("pnl_pct") or 0.0)
        reason  = str(lt.get("reason") or "--")
        entry_p = float(snap.get("entry_price") or 0.0) if side == "BUY" else 0.0
        cor_s   = GREEN if side == "BUY" else RED
        cor_pnl = GREEN if pnl >= 0 else RED
        s = "+" if pnl >= 0 else ""

        self._lt["tipo"].configure(text=side, text_color=cor_s)
        if entry_p > 0:
            self._lt["entrada"].configure(text=f"R$ {entry_p:,.2f}")
        self._lt["saida"].configure(text=f"R$ {price:,.2f}")
        self._lt["pnl"].configure(text=f"{s}R$ {pnl:.4f} ({s}{pnl_pct:.3f}%)", text_color=cor_pnl)
        self._lt["motivo"].configure(text=reason[:22])

        ts_str = str(lt.get("timestamp") or "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                diff = datetime.utcnow() - ts
                mins = int(diff.total_seconds() / 60)
                self._lt["tempo"].configure(text=f"{mins}m atrás" if mins < 60 else f"{mins//60}h atrás")
            except Exception:
                self._lt["tempo"].configure(text="recente")

    def _update_timing(self, snap: dict, ctx: dict) -> None:
        pausa      = str(snap.get("pause_until") or "")
        cross      = int(snap.get("total_cross") or 0)
        filtrados  = int(snap.get("cross_filtrados") or 0)
        last_trade = snap.get("last_trade")

        if last_trade:
            ts_str = str(last_trade.get("timestamp") or "")
            if ts_str:
                try:
                    ts   = datetime.fromisoformat(ts_str)
                    diff = int((datetime.utcnow() - ts).total_seconds())
                    self._tm["desde_trade"].configure(text=f"{diff}s atrás" if diff < 3600
                                                       else f"{diff//3600}h {(diff%3600)//60}m")
                except Exception:
                    self._tm["desde_trade"].configure(text="--")
        else:
            self._tm["desde_trade"].configure(text="Nenhum")

        ratio = (filtrados / cross * 100) if cross > 0 else 0
        cor_ot = GREEN if ratio < 80 else YELLOW if ratio < 95 else RED
        self._tm["overtrading"].configure(text=f"{ratio:.0f}% filtrado", text_color=cor_ot)
        self._tm["pausa"].configure(text=pausa[:16] if pausa else "Liberado",
                                    text_color=RED if pausa else GREEN)
        self._tm["cross"].configure(text=f"{cross} (exec: {int(snap.get('cross_executados',0))})")

    def _update_alert(self, snap: dict, dbg: dict) -> None:
        regime   = str(dbg.get("regime") or snap.get("strategy_mode_active") or "").lower()
        position = bool(snap.get("position_open", False))
        dd       = float(snap.get("current_drawdown_pct") or 0.0)
        paused   = bool(snap.get("paused_by_drawdown", False))
        cascade  = bool(dbg.get("cascade_bull") or False)
        strength = float(snap.get("signal_strength") or 0.0)
        warming  = bool((snap.get("last_signal_context") or {}).get("warming_up", False))
        offline  = self._ticks_sem_dados >= _OFFLINE_WARN

        if offline:
            self._set_alert("🔌  Sem dados de mercado — verifique a conexão", YELLOW, "#2D2200")
        elif warming:
            self._set_alert(f"⏳  Aquecendo indicadores — aguarde {(snap.get('last_signal_context') or {}).get('buffer_len',0)} ticks", BLUE, "#0F2A3D")
        elif paused:
            self._set_alert("🔴  Bot pausado — drawdown máximo atingido!", RED, "#2D0F0F")
        elif dd >= 8:
            self._set_alert(f"⚠  Drawdown alto: {dd:.1f}% — reduzindo exposição", YELLOW, "#2D1F0F")
        elif position:
            entry = float(snap.get("entry_price") or 0.0)
            sl    = float(snap.get("stop_loss")   or 0.0)
            tp    = float(snap.get("take_profit")  or 0.0)
            self._set_alert(
                f"💼  Posição aberta | Entrada R${entry:,.2f} | SL R${sl:,.2f} | TP R${tp:,.2f}",
                BLUE, "#0F1E2D")
        elif "forte" in regime and cascade and strength >= 0.7:
            self._set_alert("🔥  Tendência forte + cascata confirmada — modo agressivo", GREEN, "#0F2D1A")
        elif "forte" in regime:
            self._set_alert("🟢  Tendência confirmada — monitorando entrada", GREEN, "#0F2D1A")
        elif "lateral" in regime:
            self._set_alert("🟡  Mercado lateral — bot aguardando rompimento", YELLOW, "#2D2200")
        else:
            self._set_alert("⏸  Aguardando confluência de mercado...", TEXT_SEC, CARD_BG2)

    def _set_alert(self, text: str, text_color: str, bg: str) -> None:
        self.alert_frame.configure(fg_color=bg)
        self.alert_label.configure(text=text, text_color=text_color)

    # ══════════════════════════════════════════════════════════════════════════
    # ANIMAÇÃO DE PREÇO
    # ══════════════════════════════════════════════════════════════════════════
    def _atualizar_preco_animado(self, preco: float) -> None:
        texto, cor = self._montar_texto_preco(preco)
        self.preco_label.configure(text=texto)
        self._animar_cor_label(self.preco_label, self._preco_color_atual, cor, 8, 28)
        self._preco_color_atual = cor

    def _montar_texto_preco(self, preco: float) -> tuple[str, str]:
        if not self.preco_anterior:
            self.preco_anterior = preco
            return f"BTC/USDT: ${preco:,.2f}", TEXT_PRI
        var = ((preco - self.preco_anterior) / self.preco_anterior) * 100
        cor = GREEN if var > 0 else RED if var < 0 else TEXT_PRI
        s   = "+" if var > 0 else ""
        self.preco_anterior = preco
        return f"BTC/USDT: ${preco:,.2f} ({s}{var:.2f}%)", cor

    def _animar_cor_label(self, label, cor_ini: str, cor_fim: str,
                           passos: int, ms: int) -> None:
        if self._preco_anim_id:
            self.after_cancel(self._preco_anim_id)
            self._preco_anim_id = None
        ri = _hex_to_rgb(cor_ini)
        rf = _hex_to_rgb(cor_fim)
        def _step(i: int) -> None:
            p = i / max(1, passos)
            c = (int(ri[0]+(rf[0]-ri[0])*p), int(ri[1]+(rf[1]-ri[1])*p), int(ri[2]+(rf[2]-ri[2])*p))
            label.configure(text_color=_rgb_to_hex(c))
            if i < passos:
                self._preco_anim_id = self.after(ms, lambda: _step(i+1))
        _step(0)

    # ══════════════════════════════════════════════════════════════════════════
    # CONTROLES
    # ══════════════════════════════════════════════════════════════════════════
    def _toggle_execucao(self) -> None:
        if not self.bot_running:
            if self.modo_operacao == "desligado":
                messagebox.showwarning("Modo", "Ligue o modo real ou simulação antes de iniciar.")
                return
            self.bot_running = True
            self.bot_button.configure(text="⏹  PARAR BOT", fg_color="#7f1d1d", hover_color="#b91c1c")
            if self.bot_controller:
                try:
                    self.bot_controller.start()
                except Exception as e:
                    self.logger.error("Erro ao iniciar bot: %s", e)
        else:
            self.bot_running = False
            self.bot_button.configure(text="▶  INICIAR BOT", fg_color="#166534", hover_color="#15803d")
            if self.bot_controller:
                try:
                    self.bot_controller.stop_bot()
                except Exception as e:
                    self.logger.error("Erro ao parar bot: %s", e)
        self._update_status_footer()

    def _alternar_modo_real(self) -> None:
        if self.real_mode_switch.get() == 1:
            self.simulacao_mode_switch.deselect()
            self.modo_operacao = "real"
            if self.bot_controller:
                self.bot_controller.set_mode("real")
        elif self.simulacao_mode_switch.get() == 1:
            self.modo_operacao = "simulacao"
        else:
            self.modo_operacao = "desligado"
            self._parar_bot_ui()
        self._update_status_footer()

    def _alternar_modo_simulacao(self) -> None:
        if self.simulacao_mode_switch.get() == 1:
            self.real_mode_switch.deselect()
            self.modo_operacao = "simulacao"
            if self.bot_controller:
                self.bot_controller.set_mode("simulacao")
        elif self.real_mode_switch.get() == 1:
            self.modo_operacao = "real"
        else:
            self.modo_operacao = "desligado"
            self._parar_bot_ui()
        self._update_status_footer()

    def _parar_bot_ui(self) -> None:
        self.bot_running = False
        self.bot_button.configure(text="▶  INICIAR BOT", fg_color="#166534", hover_color="#15803d")

    def _abrir_modal_simulacao(self) -> None:
        from interface.janela_simulacao import JanelaSimulacao
        modal = JanelaSimulacao(
            self,
            config=self.bot_controller.config if self.bot_controller else {},
            on_save=lambda data: self.bot_controller.update_config(data) if self.bot_controller else None,
        )

    def _update_status_footer(self) -> None:
        modos = {"simulacao": "MODO SIMULAÇÃO", "real": "MODO REAL", "desligado": "DESLIGADO"}
        modo  = modos.get(self.modo_operacao, "DESLIGADO")
        pref  = "RODANDO" if self.bot_running else "PARADO"
        self.status_label.configure(text=f"{pref}: {modo}")

    # compatibilidade
    def _atualizar_grafico(self) -> None:
        pass