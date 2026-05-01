"""
trading_tab.py — Interface de trading reformulada.

Blocos implementados:
  1. Status do Mercado — Regime, força, distância EMAs
  2. Estrutura das EMAs — EMA9, EMA21, EMA38, alinhamento
  3. Decisão do Bot — Ação, motivo, confiança
  4. Filtros — passou/falhou em cada critério
  5. Position Sizing — saldo, risco, valor do trade
  6. Performance Rápida — trades, win rate, PnL, drawdown
  7. Último Trade — tipo, entrada, saída, PnL, motivo, tempo
  8. Alerta Inteligente — banner contextual em tempo real
"""
from __future__ import annotations

import logging
from tkinter import messagebox
from typing import Callable, Any

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from interface.theme import (
    ACCENT, APP_BG, CARD_BG, CARD_BORDER,
    FONT_LABEL, FONT_SECTION, FONT_SMALL, FONT_TITLE, FONT_VALUE,
    GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY,
)

YELLOW  = "#F59E0B"
BLUE    = "#38BDF8"
PURPLE  = "#A78BFA"
ORANGE  = "#FB923C"
GRAY_DIM = "#475569"


# ─── Helpers de cor ──────────────────────────────────────────────────────────
def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    h = color_hex.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _mix(a: str, b: str, f: float) -> str:
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    f = max(0.0, min(1.0, f))
    return _rgb_to_hex((int(ra*f + rb*(1-f)), int(ga*f + gb*(1-f)), int(ba*f + bb*(1-f))))


# ─── Card builder ────────────────────────────────────────────────────────────
def _card(parent, title: str, height: int | None = None) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    """Cria um card com título e retorna (card_frame, body_frame)."""
    kw: dict = {"fg_color": CARD_BG, "corner_radius": 12, "border_width": 1, "border_color": CARD_BORDER}
    if height:
        kw["height"] = height
    card = ctk.CTkFrame(parent, **kw)
    if title:
        ctk.CTkLabel(card, text=title, font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(
            anchor="w", padx=12, pady=(8, 2))
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
    return card, body


class TradingTab(ctk.CTkFrame):
    def __init__(self, master, market_data, trade_manager,
                 bot_controller=None,
                 on_trade_update: Callable[[], None] | None = None):
        super().__init__(master, fg_color=APP_BG)
        self.logger = logging.getLogger(__name__)
        self.market_data   = market_data
        self.trade_manager = trade_manager
        self.bot_controller = bot_controller
        self.on_trade_update = on_trade_update

        self.bot_running      = False
        self.preco_anterior: float | None = None
        self.modo_operacao    = "desligado"
        self.total_trades     = 0

        self._ultimo_preco_brl:   float = 0.0
        self._ultimo_preco_usdt:  float = 0.0
        self._preco_color_atual   = TEXT_PRIMARY
        self._preco_anim_after_id: str | None = None
        self._pulse_after_id:      str | None = None
        self._peak_balance_brl:    float = 0.0

        self.max_candles = 180
        self.prices: list[float] = []

        self._snapshot: dict[str, Any] = {}

        self._build_layout()
        self._build_chart()
        self._update_status_footer()
        self._loop_atualizar()

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_layout(self) -> None:
        # ── Cabeçalho ─────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=16,
                           border_width=1, border_color=CARD_BORDER)
        hdr.pack(fill="x", padx=18, pady=(14, 8))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=18, pady=12)

        self.preco_label = ctk.CTkLabel(left, text="BTC/USDT: --",
                                        font=FONT_TITLE, text_color=TEXT_PRIMARY)
        self.preco_label.pack(anchor="w")

        sig_row = ctk.CTkFrame(left, fg_color="transparent")
        sig_row.pack(anchor="w", pady=(6, 0))

        self.buy_indicator = ctk.CTkLabel(sig_row, text="●",
                                          font=("Segoe UI", 16, "bold"), text_color=CARD_BORDER)
        self.buy_indicator.pack(side="left")
        ctk.CTkLabel(sig_row, text="Compra", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(
            side="left", padx=(4, 14))

        self.sell_indicator = ctk.CTkLabel(sig_row, text="●",
                                           font=("Segoe UI", 16, "bold"), text_color=CARD_BORDER)
        self.sell_indicator.pack(side="left")
        ctk.CTkLabel(sig_row, text="Venda", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(
            side="left", padx=(4, 14))

        self.drawdown_label = ctk.CTkLabel(sig_row, text="Drawdown: 0.00%",
                                           font=FONT_VALUE, text_color=GREEN)
        self.drawdown_label.pack(side="left")

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=18, pady=12)

        self.saldo_label = ctk.CTkLabel(right, text="Saldo: --",
                                        font=FONT_LABEL, text_color=TEXT_PRIMARY)
        self.saldo_label.pack(anchor="e")
        self.lucro_label = ctk.CTkLabel(right, text="Lucro Hoje: R$0,00",
                                        font=FONT_VALUE, text_color=TEXT_PRIMARY)
        self.lucro_label.pack(anchor="e", pady=(4, 0))

        # ── Alerta inteligente ────────────────────────────────────────────────
        self.alert_frame = ctk.CTkFrame(self, fg_color="#1E293B", corner_radius=10,
                                        border_width=1, border_color=CARD_BORDER)
        self.alert_frame.pack(fill="x", padx=18, pady=(0, 6))
        self.alert_label = ctk.CTkLabel(self.alert_frame,
                                        text="⏳  Aguardando dados do mercado...",
                                        font=FONT_LABEL, text_color=TEXT_SECONDARY)
        self.alert_label.pack(padx=14, pady=8, anchor="w")

        # ── Corpo principal ───────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=APP_BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        # Coluna esquerda — gráfico + painel de análise
        left_col = ctk.CTkFrame(body, fg_color=APP_BG)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_col.grid_rowconfigure(0, weight=3)
        left_col.grid_rowconfigure(1, weight=2)
        left_col.grid_columnconfigure(0, weight=1)

        self.chart_frame = ctk.CTkFrame(left_col, fg_color=CARD_BG, corner_radius=16,
                                        border_width=1, border_color=CARD_BORDER)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        # Painel de análise — 3 colunas
        analysis = ctk.CTkFrame(left_col, fg_color=APP_BG)
        analysis.grid(row=1, column=0, sticky="nsew")
        analysis.grid_columnconfigure(0, weight=1)
        analysis.grid_columnconfigure(1, weight=1)
        analysis.grid_columnconfigure(2, weight=1)

        self._build_market_status_block(analysis, col=0)
        self._build_ema_block(analysis, col=1)
        self._build_decision_block(analysis, col=2)

        # Coluna direita — controles + blocos extras
        right_col = ctk.CTkFrame(body, fg_color=APP_BG)
        right_col.grid(row=0, column=1, sticky="nsew")

        self._build_controls(right_col)
        self._build_filters_block(right_col)
        self._build_sizing_block(right_col)
        self._build_performance_block(right_col)
        self._build_last_trade_block(right_col)

        # ── Rodapé ────────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=10,
                              border_width=1, border_color=CARD_BORDER)
        footer.pack(fill="x", padx=18, pady=(0, 12))
        self.status_label = ctk.CTkLabel(footer, text="PARADO: DESLIGADO",
                                         font=FONT_LABEL, text_color=TEXT_PRIMARY)
        self.status_label.pack(padx=14, pady=8, anchor="w")

    # ── Bloco 1: Status do Mercado ─────────────────────────────────────────────
    def _build_market_status_block(self, parent, col: int) -> None:
        card, body = _card(parent, "STATUS DO MERCADO")
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 6))

        self.regime_icon  = ctk.CTkLabel(body, text="⏳", font=("Segoe UI", 22))
        self.regime_icon.pack(pady=(4, 0))

        self.regime_label = ctk.CTkLabel(body, text="AGUARDANDO",
                                         font=("Segoe UI", 13, "bold"), text_color=TEXT_SECONDARY)
        self.regime_label.pack()

        self.tendencia_label = ctk.CTkLabel(body, text="Força: --",
                                            font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.tendencia_label.pack(pady=(2, 0))

        ctk.CTkFrame(body, fg_color=CARD_BORDER, height=1).pack(fill="x", pady=6)

        row1 = ctk.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(row1, text="DIST EMA9-21", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(side="left")
        self.dist_label = ctk.CTkLabel(row1, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
        self.dist_label.pack(side="right")

        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", pady=(3, 0))
        ctk.CTkLabel(row2, text="SLOPE EMA38", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(side="left")
        self.slope38_label = ctk.CTkLabel(row2, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
        self.slope38_label.pack(side="right")

        row3 = ctk.CTkFrame(body, fg_color="transparent")
        row3.pack(fill="x", pady=(3, 0))
        ctk.CTkLabel(row3, text="BUFFER", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(side="left")
        self.buffer_label = ctk.CTkLabel(row3, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
        self.buffer_label.pack(side="right")

    # ── Bloco 2: Estrutura das EMAs ───────────────────────────────────────────
    def _build_ema_block(self, parent, col: int) -> None:
        card, body = _card(parent, "ESTRUTURA DAS EMAs")
        card.grid(row=0, column=col, sticky="nsew", padx=(3, 3))

        self.align_icon  = ctk.CTkLabel(body, text="◈", font=("Segoe UI", 20))
        self.align_icon.pack(pady=(4, 0))
        self.align_label = ctk.CTkLabel(body, text="--",
                                        font=("Segoe UI", 11, "bold"), text_color=TEXT_SECONDARY)
        self.align_label.pack()

        ctk.CTkFrame(body, fg_color=CARD_BORDER, height=1).pack(fill="x", pady=6)

        for name, attr in [("EMA 9", "ema9_val"), ("EMA 21", "ema21_val"), ("EMA 38", "ema38_val")]:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=name, font=FONT_SMALL, text_color=TEXT_SECONDARY, width=50).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
            lbl.pack(side="right")
            setattr(self, attr, lbl)

        ctk.CTkFrame(body, fg_color=CARD_BORDER, height=1).pack(fill="x", pady=6)

        self.cascade_label = ctk.CTkLabel(body, text="Cascata: --",
                                          font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.cascade_label.pack()

    # ── Bloco 3: Decisão do Bot ───────────────────────────────────────────────
    def _build_decision_block(self, parent, col: int) -> None:
        card, body = _card(parent, "DECISÃO DO BOT")
        card.grid(row=0, column=col, sticky="nsew", padx=(6, 0))

        self.decision_icon  = ctk.CTkLabel(body, text="🤔", font=("Segoe UI", 22))
        self.decision_icon.pack(pady=(4, 0))
        self.decision_action = ctk.CTkLabel(body, text="AGUARDANDO",
                                            font=("Segoe UI", 13, "bold"), text_color=TEXT_SECONDARY)
        self.decision_action.pack()

        ctk.CTkFrame(body, fg_color=CARD_BORDER, height=1).pack(fill="x", pady=6)

        ctk.CTkLabel(body, text="MOTIVO", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
        self.decision_reason = ctk.CTkLabel(body, text="--", font=FONT_SMALL,
                                            text_color=TEXT_PRIMARY, wraplength=160, justify="left")
        self.decision_reason.pack(anchor="w", pady=(2, 6))

        ctk.CTkLabel(body, text="CONFIANÇA", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")

        bar_frame = ctk.CTkFrame(body, fg_color=APP_BG, corner_radius=6, height=14)
        bar_frame.pack(fill="x", pady=(2, 0))
        bar_frame.pack_propagate(False)
        self.confidence_bar = ctk.CTkProgressBar(bar_frame, height=12, corner_radius=6,
                                                  fg_color=CARD_BORDER, progress_color=GREEN)
        self.confidence_bar.pack(fill="x", padx=2, pady=2)
        self.confidence_bar.set(0)

        self.confidence_pct = ctk.CTkLabel(body, text="0%", font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.confidence_pct.pack(anchor="e")

    # ── Controles (painel direito) ─────────────────────────────────────────────
    def _build_controls(self, parent) -> None:
        ctrl = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=CARD_BORDER)
        ctrl.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(ctrl, text="CONTROLES", font=FONT_SECTION, text_color=TEXT_PRIMARY).pack(pady=(12, 8))

        self.real_mode_switch = ctk.CTkSwitch(ctrl, text="Modo Real",
                                              font=FONT_LABEL, progress_color=ACCENT,
                                              command=self._alternar_modo_real)
        self.real_mode_switch.pack(pady=(0, 4))

        self.simulacao_mode_switch = ctk.CTkSwitch(ctrl, text="Modo Simulação",
                                                   font=FONT_LABEL, progress_color=ACCENT,
                                                   command=self._alternar_modo_simulacao)
        self.simulacao_mode_switch.pack(pady=(0, 10))

        self.simulacao_button = ctk.CTkButton(ctrl, text="⚙ Configurar Simulação",
                                              height=34, font=FONT_SMALL,
                                              fg_color="#334155", hover_color="#475569",
                                              command=self._abrir_modal_simulacao)
        self.simulacao_button.pack(pady=(0, 6), padx=16, fill="x")

        self.bot_button = ctk.CTkButton(ctrl, text="▶  INICIAR BOT",
                                        height=40, font=FONT_VALUE,
                                        fg_color=GREEN, hover_color="#16A34A",
                                        command=self._toggle_execucao)
        self.bot_button.pack(pady=(0, 14), padx=16, fill="x")

    # ── Bloco 4: Filtros ──────────────────────────────────────────────────────
    def _build_filters_block(self, parent) -> None:
        card, body = _card(parent, "FILTROS DE ENTRADA")
        card.pack(fill="x", pady=(0, 6))

        self._filter_labels: dict[str, ctk.CTkLabel] = {}
        filters = [
            ("cascade",  "EMA Alinhada (9>21>38)"),
            ("slope",    "Slope EMA9 positivo"),
            ("dist",     "Distância mínima"),
            ("slope38",  "Slope EMA38 positivo"),
            ("atr",      "ATR gate ok"),
        ]
        for key, text in filters:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            icon_lbl = ctk.CTkLabel(row, text="◌", font=("Segoe UI", 13, "bold"), text_color=CARD_BORDER, width=20)
            icon_lbl.pack(side="left")
            ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(side="left", padx=(4, 0))
            self._filter_labels[key] = icon_lbl

    # ── Bloco 5: Position Sizing ───────────────────────────────────────────────
    def _build_sizing_block(self, parent) -> None:
        card, body = _card(parent, "POSITION SIZING")
        card.pack(fill="x", pady=(0, 6))

        self._sz_labels: dict[str, ctk.CTkLabel] = {}
        rows = [("saldo", "Saldo"), ("risco", "Risco usado"), ("valor", "Valor trade"), ("tipo", "Tipo")]
        for key, text in rows:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=TEXT_SECONDARY, width=90).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
            lbl.pack(side="right")
            self._sz_labels[key] = lbl

    # ── Bloco 6: Performance ──────────────────────────────────────────────────
    def _build_performance_block(self, parent) -> None:
        card, body = _card(parent, "PERFORMANCE")
        card.pack(fill="x", pady=(0, 6))

        self._perf_labels: dict[str, ctk.CTkLabel] = {}
        rows = [("trades", "Trades"), ("winrate", "Win rate"), ("pnl", "PnL"),
                ("drawdown", "Drawdown"), ("modo", "Modo")]
        for key, text in rows:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=TEXT_SECONDARY, width=80).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
            lbl.pack(side="right")
            self._perf_labels[key] = lbl

    # ── Bloco 7: Último Trade ─────────────────────────────────────────────────
    def _build_last_trade_block(self, parent) -> None:
        card, body = _card(parent, "ÚLTIMO TRADE")
        card.pack(fill="x", pady=(0, 6))

        self._lt_labels: dict[str, ctk.CTkLabel] = {}
        rows = [("tipo", "Tipo"), ("entrada", "Entrada"), ("saida", "Saída"),
                ("pnl", "PnL"), ("motivo", "Motivo"), ("tempo", "Duração")]
        for key, text in rows:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=TEXT_SECONDARY, width=60).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", font=FONT_SMALL, text_color=TEXT_PRIMARY)
            lbl.pack(side="right")
            self._lt_labels[key] = lbl

    # ═══════════════════════════════════════════════════════════════════════════
    # GRÁFICO
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_chart(self) -> None:
        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_facecolor(APP_BG)
        self.price_line,    = self.ax.plot([], [], color=TEXT_PRIMARY,  linewidth=1.8, alpha=0.95, label="BTC")
        self.ema9_line,     = self.ax.plot([], [], color=GREEN,          linewidth=1.2, alpha=0.9,  label="EMA9")
        self.ema21_line,    = self.ax.plot([], [], color=RED,            linewidth=1.2, alpha=0.9,  label="EMA21")
        self.ema38_line,    = self.ax.plot([], [], color=YELLOW,         linewidth=1.2, alpha=0.85, label="EMA38", linestyle="--")
        self.ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
        self.ax.grid(color=CARD_BORDER, alpha=0.35)
        self.ax.legend(loc="upper left", fontsize=7, facecolor=CARD_BG,
                       labelcolor=TEXT_PRIMARY, framealpha=0.7)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    # ═══════════════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL
    # ═══════════════════════════════════════════════════════════════════════════
    def _loop_atualizar(self) -> None:
        try:
            self._coletar_precos()
            self._atualizar_grafico_linhas()
            self._atualizar_snapshot()
            self._atualizar_todos_blocos()
        except Exception as e:
            self.logger.exception("Erro no loop: %s", e)
        self.after(1000, self._loop_atualizar)

    def _coletar_precos(self) -> None:
        try:
            usdt = float(self.market_data.pegar_preco_atual("BTCUSDT") or 0.0)
        except Exception:
            usdt = 0.0
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
                self._snapshot = self.bot_controller.get_runtime_snapshot() or {}
            except Exception:
                pass
        else:
            self._snapshot = {}

    def _atualizar_grafico_linhas(self) -> None:
        if not self.prices:
            return
        x = np.arange(len(self.prices))
        y = np.array(self.prices)
        self.price_line.set_data(x, y)

        dbg = self._snapshot.get("strategy_debug") or {}

        def _ema_series(attr: str, period: int) -> np.ndarray | None:
            # Tenta pegar do snapshot, senão calcula localmente com convolução
            val = dbg.get(attr)
            if val and val > 0 and len(y) > 0:
                return None  # será atualizado pontualmente no bloco de EMAs
            if len(y) >= period:
                return np.convolve(y, np.ones(period) / period, mode="valid")
            return None

        if len(y) >= 9:
            ma9 = np.convolve(y, np.ones(9) / 9, mode="valid")
            self.ema9_line.set_data(x[-len(ma9):], ma9)
        else:
            self.ema9_line.set_data([], [])

        if len(y) >= 21:
            ma21 = np.convolve(y, np.ones(21) / 21, mode="valid")
            self.ema21_line.set_data(x[-len(ma21):], ma21)
        else:
            self.ema21_line.set_data([], [])

        if len(y) >= 38:
            ma38 = np.convolve(y, np.ones(38) / 38, mode="valid")
            self.ema38_line.set_data(x[-len(ma38):], ma38)
        else:
            self.ema38_line.set_data([], [])

        if len(self.prices) > 2:
            self.ax.set_xlim(max(0, len(self.prices) - self.max_candles), len(self.prices))
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ═══════════════════════════════════════════════════════════════════════════
    # ATUALIZAÇÃO DOS BLOCOS
    # ═══════════════════════════════════════════════════════════════════════════
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
        self._update_alert(snap, dbg)

    # ── Cabeçalho ─────────────────────────────────────────────────────────────
    def _update_header(self, snap: dict) -> None:
        equity  = float(snap.get("equity_brl") or 0.0)
        lucro   = float(snap.get("lucro_hoje_brl") or 0.0)
        dd      = float(snap.get("current_drawdown_pct") or 0.0)

        if equity > 0:
            self.saldo_label.configure(text=f"Saldo: R$ {equity:,.2f}")
        cor_l = GREEN if lucro >= 0 else RED
        sinal = "+" if lucro >= 0 else ""
        self.lucro_label.configure(text=f"Lucro Hoje: {sinal}R$ {lucro:,.4f}", text_color=cor_l)

        cor_dd = GREEN if dd < 5 else YELLOW if dd < 10 else RED
        self.drawdown_label.configure(text=f"Drawdown: {dd:+.2f}%", text_color=cor_dd)

    # ── Bloco 1: Status do Mercado ─────────────────────────────────────────────
    def _update_market_status(self, snap: dict, dbg: dict, ctx: dict) -> None:
        regime = str(dbg.get("regime") or snap.get("strategy_mode_active") or "lateral").lower()
        warming = bool(ctx.get("warming_up", False))
        buf     = int(ctx.get("buffer_len") or dbg.get("buffer_len") or 0)
        req     = int(ctx.get("required_periods") or dbg.get("buffer_len") or 38)
        dist_pct = float(ctx.get("distancia_percentual") or dbg.get("dist_pct") or 0.0)
        slope38  = float(ctx.get("slope_ema38") or dbg.get("slope38") or 0.0)
        slope_pct= float(dbg.get("regime_slope_pct") or 0.0)

        if warming:
            self.regime_icon.configure(text="⏳")
            self.regime_label.configure(text=f"AQUECENDO {buf}/{req}", text_color=TEXT_SECONDARY)
            self.tendencia_label.configure(text="Força: --", text_color=TEXT_SECONDARY)
        elif "lateral" in regime:
            self.regime_icon.configure(text="🟡")
            self.regime_label.configure(text="LATERAL", text_color=YELLOW)
            self.tendencia_label.configure(text="Força: FRACA", text_color=YELLOW)
        elif "forte" in regime:
            self.regime_icon.configure(text="🟢")
            self.regime_label.configure(text="TENDÊNCIA FORTE", text_color=GREEN)
            self.tendencia_label.configure(text="Força: ALTA", text_color=GREEN)
        elif "fraca" in regime:
            self.regime_icon.configure(text="🟡")
            self.regime_label.configure(text="TENDÊNCIA FRACA", text_color=YELLOW)
            self.tendencia_label.configure(text="Força: MÉDIA", text_color=YELLOW)
        else:
            self.regime_icon.configure(text="🔴")
            self.regime_label.configure(text="INDEFINIDO", text_color=RED)
            self.tendencia_label.configure(text="Força: --", text_color=TEXT_SECONDARY)

        dist_str = f"{dist_pct*100:.5f}%"
        cor_dist = GREEN if dist_pct >= 0.0005 else (YELLOW if dist_pct >= 0.0003 else RED)
        self.dist_label.configure(text=dist_str, text_color=cor_dist)

        cor_s38 = GREEN if slope38 > 0 else RED
        self.slope38_label.configure(text=f"{slope38:+.2f}", text_color=cor_s38)
        self.buffer_label.configure(text=f"{buf}/{req}")

    # ── Bloco 2: Estrutura das EMAs ───────────────────────────────────────────
    def _update_ema_block(self, dbg: dict, ctx: dict) -> None:
        e9  = float(ctx.get("ema9")  or dbg.get("ema9")  or 0.0)
        e21 = float(ctx.get("ema21") or dbg.get("ema21") or 0.0)
        e38 = float(ctx.get("ema38") or dbg.get("ema38") or 0.0)
        cascade_bull = bool(ctx.get("cascade_bull") or dbg.get("cascade_bull") or False)
        cascade_bear = bool(ctx.get("cascade_bear") or dbg.get("cascade_bear") or False)

        def _fmt(v: float, ref: float) -> tuple[str, str]:
            if v <= 0:
                return "--", TEXT_SECONDARY
            cor = GREEN if v > ref else RED if v < ref else TEXT_PRIMARY
            return f"{v:,.2f}", cor

        if e21 > 0:
            t9,  c9  = _fmt(e9,  e21)
            t21, c21 = f"{e21:,.2f}", TEXT_PRIMARY
            t38, c38 = _fmt(e38, e21)
            self.ema9_val.configure(text=t9,  text_color=c9)
            self.ema21_val.configure(text=t21, text_color=c21)
            self.ema38_val.configure(text=t38, text_color=c38)
        else:
            for lbl in (self.ema9_val, self.ema21_val, self.ema38_val):
                lbl.configure(text="--", text_color=TEXT_SECONDARY)

        if cascade_bull:
            self.align_icon.configure(text="🟢")
            self.align_label.configure(text="ALTA (9>21>38)", text_color=GREEN)
            self.cascade_label.configure(text="Cascata: ✔ confirmada", text_color=GREEN)
        elif cascade_bear:
            self.align_icon.configure(text="🔴")
            self.align_label.configure(text="BAIXA (9<21<38)", text_color=RED)
            self.cascade_label.configure(text="Cascata: ✔ baixa", text_color=RED)
        else:
            self.align_icon.configure(text="🟡")
            self.align_label.configure(text="SEM ALINHAMENTO", text_color=YELLOW)
            self.cascade_label.configure(text="Cascata: ✖ não confirmada", text_color=YELLOW)

    # ── Bloco 3: Decisão ─────────────────────────────────────────────────────
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

        # Razão legível
        reason_map = {
            "mercado_lateral_bloqueado":     "EMA colada (mercado lateral)",
            "mercado_lateral_sem_operacao":  "Mercado lateral — aguardando",
            "cascata_nao_alinhada":          "EMAs fora de cascata",
            "dist_insuficiente":             "Distância EMA insuficiente",
            "slope_negativo":                "Slope EMA9 negativo",
            "atr_gate_nao_atingido":         "Volatilidade insuficiente",
            "posicao_mantida":               "Posição aberta — mantendo",
            "crossover_alta_cascata_confirmado": "Crossover + cascata confirmados",
            "tendencia_cascata_agressiva":   "Tendência forte — modo agressivo",
            "cascata_ok_aguardando_crossover": "Cascata ok — aguardando crossover",
            "dados_insuficientes":           "Aquecendo indicadores...",
        }
        reason_show = reason
        for k, v in reason_map.items():
            if k in reason:
                reason_show = v
                break

        self.decision_reason.configure(text=reason_show)
        self.confidence_bar.set(strength)

        cor_bar = GREEN if strength >= 0.7 else YELLOW if strength >= 0.4 else RED
        self.confidence_bar.configure(progress_color=cor_bar)
        self.confidence_pct.configure(text=f"{int(strength*100)}%",
                                      text_color=cor_bar)

    # ── Bloco 4: Filtros ──────────────────────────────────────────────────────
    def _update_filters(self, dbg: dict, ctx: dict) -> None:
        cascade_bull = bool(ctx.get("cascade_bull") or dbg.get("cascade_bull") or False)
        slope9  = float(ctx.get("slope_ema9")  or dbg.get("slope9")  or 0.0)
        slope38 = float(ctx.get("slope_ema38") or dbg.get("slope38") or 0.0)
        dist    = float(ctx.get("distancia_percentual") or dbg.get("dist_pct") or 0.0)
        atr     = float(ctx.get("atr") or dbg.get("atr") or 0.0)
        gate    = float(ctx.get("atr_gate") or 0.0)
        e9  = float(ctx.get("ema9")  or dbg.get("ema9")  or 0.0)
        e21 = float(ctx.get("ema21") or dbg.get("ema21") or 0.0)
        dist_abs = abs(e9 - e21)

        checks = {
            "cascade": cascade_bull,
            "slope":   slope9 > 0,
            "dist":    dist >= 0.0005,
            "slope38": slope38 > 0,
            "atr":     (gate <= 0) or (atr <= 0) or (dist_abs >= gate),
        }
        for key, passed in checks.items():
            lbl = self._filter_labels.get(key)
            if lbl:
                lbl.configure(text="✔" if passed else "✖",
                              text_color=GREEN if passed else RED)

    # ── Bloco 5: Position Sizing ───────────────────────────────────────────────
    def _update_sizing(self, snap: dict) -> None:
        equity   = float(snap.get("equity_brl")           or 0.0)
        exposure = float(snap.get("current_exposure_brl") or 0.0)
        exp_pct  = float(snap.get("current_exposure_pct") or 0.0)
        strength = float(snap.get("signal_strength")      or
                         snap.get("last_signal_context", {}).get("signal_strength") or 0.0)

        if strength >= 0.7:
            tipo, cor_tipo = "AGRESSIVO 🔥", GREEN
        elif strength >= 0.4:
            tipo, cor_tipo = "NORMAL", BLUE
        else:
            tipo, cor_tipo = "REDUZIDO", YELLOW

        self._sz_labels["saldo"].configure(text=f"R$ {equity:,.2f}")
        self._sz_labels["risco"].configure(text=f"{exp_pct:.1f}%")
        self._sz_labels["valor"].configure(text=f"R$ {exposure:,.2f}")
        self._sz_labels["tipo"].configure(text=tipo, text_color=cor_tipo)

    # ── Bloco 6: Performance ──────────────────────────────────────────────────
    def _update_performance(self, snap: dict) -> None:
        trades  = int((snap.get("trades_lucrativos") or 0)) + int((snap.get("trades_prejuizo") or 0))
        wr      = float(snap.get("win_rate") or 0.0) * 100
        pnl     = float(snap.get("lucro_hoje_brl") or 0.0)
        dd      = float(snap.get("current_drawdown_pct") or 0.0)
        modo    = str(snap.get("strategy_mode_active") or "--").upper()

        cor_pnl = GREEN if pnl >= 0 else RED
        sinal   = "+" if pnl >= 0 else ""

        self._perf_labels["trades"].configure(text=str(trades))
        self._perf_labels["winrate"].configure(text=f"{wr:.1f}%",
                                               text_color=GREEN if wr >= 50 else YELLOW)
        self._perf_labels["pnl"].configure(text=f"{sinal}R$ {pnl:.4f}", text_color=cor_pnl)
        self._perf_labels["drawdown"].configure(text=f"{dd:.2f}%",
                                                text_color=GREEN if dd < 5 else YELLOW if dd < 10 else RED)
        self._perf_labels["modo"].configure(text=modo)

    # ── Bloco 7: Último Trade ─────────────────────────────────────────────────
    def _update_last_trade(self, snap: dict) -> None:
        lt = snap.get("last_trade")
        if not lt:
            return

        side    = str(lt.get("side") or "--")
        price   = float(lt.get("price") or 0.0)
        pnl     = float(lt.get("pnl_brl") or 0.0)
        pnl_pct = float(lt.get("pnl_pct") or 0.0)
        reason  = str(lt.get("reason") or "--")

        entry_price = float(snap.get("entry_price") or 0.0) if side == "BUY" else 0.0
        cor_side  = GREEN if side == "BUY" else RED
        cor_pnl   = GREEN if pnl >= 0 else RED
        sinal     = "+" if pnl >= 0 else ""

        self._lt_labels["tipo"].configure(text=side, text_color=cor_side)
        if entry_price > 0:
            self._lt_labels["entrada"].configure(text=f"R$ {entry_price:,.2f}")
        self._lt_labels["saida"].configure(text=f"R$ {price:,.2f}")
        self._lt_labels["pnl"].configure(
            text=f"{sinal}R$ {pnl:.4f} ({sinal}{pnl_pct:.3f}%)", text_color=cor_pnl)
        self._lt_labels["motivo"].configure(text=reason[:22])
        self._lt_labels["tempo"].configure(text="recente")

    # ── Bloco 8: Alerta Inteligente ───────────────────────────────────────────
    def _update_alert(self, snap: dict, dbg: dict) -> None:
        regime   = str(dbg.get("regime") or snap.get("strategy_mode_active") or "").lower()
        position = bool(snap.get("position_open", False))
        dd       = float(snap.get("current_drawdown_pct") or 0.0)
        paused   = bool(snap.get("paused_by_drawdown", False))
        cascade  = bool(snap.get("cascade_bull") or dbg.get("cascade_bull") or False)
        strength = float(snap.get("signal_strength") or 0.0)
        warming  = bool(snap.get("last_signal_context", {}).get("warming_up", False))

        if warming:
            self._set_alert("⏳  Aquecendo indicadores — aguarde...", BLUE, "#0F2A3D")
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
        elif "lateral" in regime:
            self._set_alert("🟡  Mercado lateral — bot aguardando tendência forte", YELLOW, "#2D2200")
        elif "forte" in regime and cascade and strength >= 0.7:
            self._set_alert("🔥  Tendência forte detectada — modo agressivo ativo", GREEN, "#0F2D1A")
        elif "forte" in regime:
            self._set_alert("🟢  Tendência confirmada — monitorando entrada", GREEN, "#0F2D1A")
        else:
            self._set_alert("⏸  Aguardando confluência de mercado...", TEXT_SECONDARY, CARD_BG)

    def _set_alert(self, text: str, text_color: str, bg: str) -> None:
        self.alert_frame.configure(fg_color=bg)
        self.alert_label.configure(text=text, text_color=text_color)

    # ═══════════════════════════════════════════════════════════════════════════
    # HELPERS DE ANIMAÇÃO E PREÇO
    # ═══════════════════════════════════════════════════════════════════════════
    def _atualizar_preco_animado(self, preco_atual: float) -> None:
        texto, cor = self._montar_texto_preco(preco_atual)
        self.preco_label.configure(text=texto)
        self._animar_cor_label(self.preco_label, self._preco_color_atual, cor, 8, 28)
        self._preco_color_atual = cor

    def _montar_texto_preco(self, preco_atual: float) -> tuple[str, str]:
        if self.preco_anterior is None or self.preco_anterior == 0:
            self.preco_anterior = preco_atual
            return f"BTC/USDT: ${preco_atual:,.2f}", TEXT_PRIMARY
        var = ((preco_atual - self.preco_anterior) / self.preco_anterior) * 100
        cor = GREEN if var > 0 else RED if var < 0 else TEXT_PRIMARY
        sinal = "+" if var > 0 else ""
        self.preco_anterior = preco_atual
        return f"BTC/USDT: ${preco_atual:,.2f} ({sinal}{var:.2f}%)", cor

    def _animar_cor_label(self, label, cor_ini: str, cor_fim: str, passos: int, ms: int) -> None:
        if self._preco_anim_after_id:
            self.after_cancel(self._preco_anim_after_id)
            self._preco_anim_after_id = None
        ri = _hex_to_rgb(cor_ini)
        rf = _hex_to_rgb(cor_fim)
        def _step(i: int) -> None:
            p = i / max(1, passos)
            c = (int(ri[0]+(rf[0]-ri[0])*p), int(ri[1]+(rf[1]-ri[1])*p), int(ri[2]+(rf[2]-ri[2])*p))
            label.configure(text_color=_rgb_to_hex(c))
            if i < passos:
                self._preco_anim_after_id = self.after(ms, lambda: _step(i+1))
        _step(0)

    def _animar_pulso_trade(self, side: str) -> None:
        if self._pulse_after_id:
            self.after_cancel(self._pulse_after_id)
            self._pulse_after_id = None
        alvo  = self.buy_indicator  if side == "BUY" else self.sell_indicator
        outro = self.sell_indicator if side == "BUY" else self.buy_indicator
        cor   = GREEN if side == "BUY" else RED
        outro.configure(text_color=CARD_BORDER)
        steps = [0.35, 0.55, 0.75, 1.0, 0.8, 0.6, 0.42, 0.3]
        def _step(i: int) -> None:
            alvo.configure(text_color=_mix(cor, CARD_BG, steps[i]))
            if i < len(steps) - 1:
                self._pulse_after_id = self.after(70, lambda: _step(i+1))
            else:
                alvo.configure(text_color=CARD_BORDER)
        _step(0)

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTROLES DO BOT
    # ═══════════════════════════════════════════════════════════════════════════
    def _toggle_execucao(self) -> None:
        if not self.bot_running:
            if self.modo_operacao == "desligado":
                messagebox.showwarning("Modo", "Ligue o modo real ou simulação antes de iniciar.")
                return
            self.bot_running = True
            self.bot_button.configure(text="⏹  PARAR BOT", fg_color=RED, hover_color="#DC2626")
            if self.bot_controller:
                try:
                    self.bot_controller.start()
                except Exception as e:
                    self.logger.error("Erro ao iniciar bot: %s", e)
        else:
            self.bot_running = False
            self.bot_button.configure(text="▶  INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")
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
            self.bot_running = False
            self.bot_button.configure(text="▶  INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")
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
            self.bot_running = False
            self.bot_button.configure(text="▶  INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")
        self._update_status_footer()

    def _abrir_modal_simulacao(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Configuração de Simulação")
        modal.geometry("420x300")
        modal.resizable(False, False)
        modal.grab_set()
        modal.configure(fg_color=APP_BG)

        for label, placeholder in [
            ("Saldo inicial (R$)", "Ex: 1000"),
            ("Máximo de compra por trade (R$)", "Ex: 100"),
            ("Máximo de venda por trade (R$)", "Ex: 100"),
        ]:
            ctk.CTkLabel(modal, text=label, font=FONT_LABEL, text_color=TEXT_PRIMARY).pack(
                pady=(12, 4), padx=20, anchor="w")
            entry = ctk.CTkEntry(modal, placeholder_text=placeholder)
            entry.pack(padx=20, fill="x")
            if "Saldo" in label:
                entry_saldo = entry
            elif "compra" in label:
                entry_comprar = entry
            else:
                entry_vender = entry

        ctk.CTkButton(modal, text="Salvar", height=38, font=FONT_LABEL,
                      fg_color=GREEN, hover_color="#16A34A",
                      command=lambda: self._salvar_simulacao(
                          entry_saldo.get(), entry_comprar.get(), entry_vender.get(), modal)
                      ).pack(pady=16, padx=20, fill="x")

    def _salvar_simulacao(self, s: str, c: str, v: str, modal) -> None:
        saldo   = self._parse_float(s)
        comprar = self._parse_float(c)
        vender  = self._parse_float(v)
        if not all([saldo, comprar, vender]):
            messagebox.showerror("Erro", "Preencha todos os valores corretamente.")
            return
        if self.bot_controller:
            self.bot_controller.update_config({
                "saldo_inicial": saldo, "capital_total": saldo,
                "max_buy_brl": comprar, "max_sell_brl": vender,
            })
        modal.destroy()

    def _parse_float(self, v: str) -> float | None:
        try:
            n = float(str(v).replace(",", "."))
            return n if n > 0 else None
        except Exception:
            return None

    def _update_status_footer(self) -> None:
        modos = {"simulacao": "MODO SIMULAÇÃO", "real": "MODO REAL", "desligado": "DESLIGADO"}
        modo  = modos.get(self.modo_operacao, "DESLIGADO")
        pref  = "RODANDO" if self.bot_running else "PARADO"
        self.status_label.configure(text=f"{pref}: {modo}")

    # mantém compatibilidade com código externo que chame estas funções
    def _atualizar_grafico(self) -> None:
        pass  # substituído por _loop_atualizar