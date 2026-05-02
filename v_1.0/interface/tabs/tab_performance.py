"""
tabs/tab_performance.py — Tab de Performance standalone.

Usado quando o projeto importa TabPerformance diretamente.
Esta versão redireciona para o sistema unificado do main_window,
mas também funciona de forma standalone com snapshot injetado.
"""
from __future__ import annotations

from typing import Any

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

APP_BG   = "#0d1117"
CARD_BG  = "#161b22"
CARD_BG2 = "#1c2128"
BORDER   = "#30363d"
GREEN    = "#22c55e"
RED      = "#ef4444"
YELLOW   = "#f59e0b"
BLUE     = "#38bdf8"
TEXT_PRI = "#e6edf3"
TEXT_SEC = "#8b949e"
ACCENT   = "#1f6feb"


def _set_box(box: ctk.CTkTextbox, content: str) -> None:
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("end", content)
    box.see("end")
    box.configure(state="disabled")


class TabPerformance(ctk.CTkFrame):
    """
    Tab de performance completa e autônoma.
    Recebe snapshots via update(snapshot).
    """

    def __init__(self, master, *args, **kwargs):
        super().__init__(master, fg_color=APP_BG, *args, **kwargs)
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=2)
        self.grid_rowconfigure(2, weight=1)

        # ── KPIs ──────────────────────────────────────────────────────────────
        z1 = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        z1.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 6))
        z1.grid_columnconfigure((0,1,2,3,4,5,6), weight=1)

        kpis = [
            ("_kpi_trades",    "Total Trades",   "0"),
            ("_kpi_winrate",   "Win Rate",       "0.00%"),
            ("_kpi_lucro",     "Lucro Líquido",  "R$ 0.00"),
            ("_kpi_dd",        "Drawdown Máx",   "0.00%"),
            ("_kpi_pf",        "Profit Factor",  "0.00"),
            ("_kpi_sharpe",    "Sharpe",         "0.00"),
            ("_kpi_exp",       "Expectância",    "R$ 0.00"),
        ]
        for idx, (attr, title, val) in enumerate(kpis):
            card = ctk.CTkFrame(z1, fg_color=CARD_BG2, corner_radius=10)
            card.grid(row=0, column=idx, sticky="nsew", padx=5, pady=8)
            ctk.CTkLabel(card, text=title, text_color=TEXT_SEC,
                         font=("JetBrains Mono", 10)).pack(anchor="w", padx=10, pady=(8,2))
            lbl = ctk.CTkLabel(card, text=val, font=("JetBrains Mono", 18, "bold"), text_color=TEXT_PRI)
            lbl.pack(anchor="w", padx=10, pady=(0, 8))
            setattr(self, attr, lbl)

        self._kpi_stats = ctk.CTkLabel(z1, text="Avg Gain: R$0.00 | Avg Loss: R$0.00",
                                        anchor="w", text_color=TEXT_SEC,
                                        font=("JetBrains Mono", 10))
        self._kpi_stats.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0,6))
        self._kpi_cross = ctk.CTkLabel(
            z1, text="Cross: 0 | Filtrados: 0 | Executados: 0 | ✔ 0 | ✖ 0",
            anchor="w", text_color=TEXT_SEC, font=("JetBrains Mono", 10))
        self._kpi_cross.grid(row=1, column=4, columnspan=3, sticky="ew", padx=14, pady=(0,6))

        # ── Gráficos ───────────────────────────────────────────────────────────
        z2 = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        z2.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

        self._perf_fig, (self._ax_eq, self._ax_hist) = plt.subplots(
            1, 2, figsize=(12, 4), gridspec_kw={"width_ratios": [3, 1]}
        )
        self._perf_fig.patch.set_facecolor(CARD_BG)
        for ax in (self._ax_eq, self._ax_hist):
            ax.set_facecolor(APP_BG)
            ax.tick_params(colors=TEXT_SEC, labelsize=8)
            ax.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)
        self._ax_eq.set_title("Equity vs Benchmark", color=TEXT_PRI, fontsize=9)
        self._ax_hist.set_title("Histograma de Trades", color=TEXT_PRI, fontsize=9)
        self._perf_fig.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(self._perf_fig, master=z2)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self._perf_canvas = canvas

        # ── Logs ──────────────────────────────────────────────────────────────
        z3 = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        z3.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0,6))
        z3.grid_columnconfigure(0, weight=2)
        z3.grid_columnconfigure(1, weight=1)
        z3.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(z3, text="Deep Logs", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).grid(row=0, column=0, sticky="w", padx=12, pady=(8,4))
        ctk.CTkLabel(z3, text="Quase-Trades", font=("JetBrains Mono", 12, "bold"),
                     text_color=TEXT_PRI).grid(row=0, column=1, sticky="w", padx=12, pady=(8,4))

        self._deep_box = ctk.CTkTextbox(z3, state="disabled",
                                         font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self._deep_box.grid(row=1, column=0, sticky="nsew", padx=(10,4), pady=(0,8))

        self._near_box = ctk.CTkTextbox(z3, state="disabled",
                                         font=("JetBrains Mono", 10), fg_color=APP_BG, text_color=TEXT_PRI)
        self._near_box.grid(row=1, column=1, sticky="nsew", padx=(4,10), pady=(0,8))

        # Confluência
        conf_panel = ctk.CTkFrame(z3, fg_color=APP_BG, corner_radius=8)
        conf_panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0,8))
        self._conf_rsi  = ctk.CTkLabel(conf_panel, text="EMA9>EMA21: 🔴", font=("JetBrains Mono", 11))
        self._conf_dist = ctk.CTkLabel(conf_panel, text="Slope EMA9: 🔴", font=("JetBrains Mono", 11))
        self._conf_vol  = ctk.CTkLabel(conf_panel, text="ATR Gate: 🔴",   font=("JetBrains Mono", 11))
        self._conf_bb   = ctk.CTkLabel(conf_panel, text="Regime: LATERAL", font=("JetBrains Mono", 11))
        self._conf_verd = ctk.CTkLabel(conf_panel, text="Aguardando confluencia",
                                        font=("JetBrains Mono", 12, "bold"), text_color=YELLOW)
        for lbl in (self._conf_rsi, self._conf_dist, self._conf_vol, self._conf_bb):
            lbl.pack(side="left", padx=12, pady=6)
        self._conf_verd.pack(side="right", padx=12, pady=6)

    # ══════════════════════════════════════════════════════════════════════════
    # ATUALIZAÇÃO
    # ══════════════════════════════════════════════════════════════════════════
    def update(self, snapshot: dict[str, Any]) -> None:
        """Atualiza toda a aba com um novo snapshot."""
        win_rate     = float(snapshot.get("win_rate", 0.0))
        pf           = float(snapshot.get("profit_factor", 0.0))
        dd_max       = float(snapshot.get("drawdown_max_pct", 0.0))
        avg_gain     = float(snapshot.get("avg_gain", 0.0))
        avg_loss     = float(snapshot.get("avg_loss", 0.0))
        total_trades = int(snapshot.get("total_trades", 0) or 0)
        lucro        = float(snapshot.get("lucro_liquido_brl", 0.0))
        sharpe       = float(snapshot.get("sharpe_simplificado", snapshot.get("sharpe", 0.0)))
        expectancy   = float(snapshot.get("expectancy", 0.0))
        eq_hist      = [float(v) for v in (snapshot.get("equity_history") or [])]
        bm_hist      = [float(v) for v in (snapshot.get("benchmark_history") or [])]
        trades       = list(snapshot.get("trade_history") or [])
        near_logs    = list(snapshot.get("near_trade_logs") or [])
        confluence   = dict(snapshot.get("confluence") or {})
        total_cross  = int(snapshot.get("total_cross", 0) or 0)
        filtrados    = int(snapshot.get("cross_filtrados", 0) or 0)
        executados   = int(snapshot.get("cross_executados", 0) or 0)
        lucrativos   = int(snapshot.get("trades_lucrativos", 0) or 0)
        prejuizo_n   = int(snapshot.get("trades_prejuizo", 0) or 0)

        # KPIs
        cor_l = GREEN if lucro >= 0 else RED
        self._kpi_trades.configure(text=str(total_trades))
        self._kpi_winrate.configure(text=f"{win_rate*100:.2f}%",
                                     text_color=GREEN if win_rate >= 0.5 else YELLOW)
        self._kpi_lucro.configure(text=f"R$ {lucro:,.2f}", text_color=cor_l)
        self._kpi_dd.configure(text=f"{dd_max:.2f}%",
                                text_color=GREEN if dd_max < 5 else YELLOW if dd_max < 10 else RED)
        self._kpi_pf.configure(text=f"{pf:.2f}",
                                text_color=GREEN if pf >= 1.3 else YELLOW if pf >= 1.0 else RED)
        self._kpi_sharpe.configure(text=f"{sharpe:.2f}",
                                    text_color=GREEN if sharpe > 0 else RED)
        self._kpi_exp.configure(text=f"R$ {expectancy:.4f}",
                                 text_color=GREEN if expectancy > 0 else RED)
        self._kpi_stats.configure(
            text=f"Avg Gain: R$ {avg_gain:.4f} | Avg Loss: R$ {avg_loss:.4f} | Expectância: R$ {expectancy:.4f}"
        )
        self._kpi_cross.configure(
            text=f"Cross: {total_cross} | Filtrados: {filtrados} | Executados: {executados} | ✔ {lucrativos} | ✖ {prejuizo_n}"
        )

        # Gráfico equity
        self._ax_eq.cla()
        self._ax_eq.set_facecolor(APP_BG)
        self._ax_eq.tick_params(colors=TEXT_SEC, labelsize=8)
        self._ax_eq.grid(color=BORDER, alpha=0.3, linestyle="--", linewidth=0.5)
        if eq_hist:
            eq = np.array(eq_hist)
            x  = np.arange(len(eq))
            self._ax_eq.plot(x, eq, color=GREEN, linewidth=1.8, label="Equity")
            peak = np.maximum.accumulate(eq)
            self._ax_eq.fill_between(x, eq, peak, where=peak >= eq,
                                      color=RED, alpha=0.12, label="Drawdown")
            if bm_hist:
                bm = np.array(bm_hist[:len(eq_hist)])
                if len(bm) > 0 and bm[0] > 0 and eq_hist[0] > 0:
                    bm_norm = (bm / bm[0]) * eq_hist[0]
                    self._ax_eq.plot(np.arange(len(bm_norm)), bm_norm, color=TEXT_SEC,
                                      linewidth=1.2, label="Benchmark BTC", linestyle="--")
        self._ax_eq.legend(loc="upper left", fontsize=7, facecolor=CARD_BG,
                            labelcolor=TEXT_PRI, framealpha=0.8)
        self._ax_eq.set_title("Equity vs Benchmark", color=TEXT_PRI, fontsize=9)

        # Histograma
        profits = [float(t.get("lucro", 0.0)) for t in trades]
        self._ax_hist.cla()
        self._ax_hist.set_facecolor(APP_BG)
        self._ax_hist.tick_params(colors=TEXT_SEC, labelsize=8)
        self._ax_hist.grid(color=BORDER, alpha=0.25, linestyle="--", linewidth=0.5)
        if profits:
            self._ax_hist.hist(profits, bins=min(20, max(5, len(profits)//2)),
                                color=BLUE, alpha=0.80, edgecolor=BORDER)
            self._ax_hist.axvline(0, color=TEXT_SEC, linewidth=0.8, linestyle="--")
        self._ax_hist.set_title("Histograma", color=TEXT_PRI, fontsize=9)
        self._perf_fig.tight_layout(pad=1.5)
        self._perf_canvas.draw_idle()

        # Deep logs
        header = "Data                | Tp | Entrada    | Saída      | Lucro      | Motivo"
        lines = [header, "─" * len(header)]
        for r in trades[-80:]:
            lines.append(
                f"{str(r.get('data',''))[:19]:19} | "
                f"{str(r.get('tipo',''))[:2]:2} | "
                f"{float(r.get('entrada',0)):10.2f} | "
                f"{float(r.get('saida',0)):10.2f} | "
                f"{float(r.get('lucro',0)):+10.4f} | "
                f"{str(r.get('motivo',''))[:28]}"
            )
        _set_box(self._deep_box, "\n".join(lines))

        # Quase-trades
        hdr2 = "Data                | BTC Preço  | Dist%    | Slope    | Motivo"
        lines2 = [hdr2, "─" * len(hdr2)]
        for r in near_logs[-100:]:
            lines2.append(
                f"{str(r.get('data',''))[:19]:19} | "
                f"{float(r.get('price_btc',0)):10.2f} | "
                f"{float(r.get('distancia_percentual',0))*100:8.5f} | "
                f"{float(r.get('slope',0)):8.4f} | "
                f"{str(r.get('reason',''))[:28]:28}"
            )
        _set_box(self._near_box, "\n".join(lines2))

        # Confluência
        self._conf_rsi.configure(
            text=f"EMA9>EMA21: {'🟢' if confluence.get('ema_above_sma') else '🔴'}")
        self._conf_dist.configure(
            text=f"Slope EMA9: {'🟢' if confluence.get('sma_slope_up') else '🔴'}")
        self._conf_vol.configure(
            text=f"ATR Gate: {'🟢' if confluence.get('distancia_ok') else '🔴'}")
        self._conf_bb.configure(
            text=f"Regime: {str(snapshot.get('strategy_mode_active','lateral')).upper()}")
        veredito = str(confluence.get("veredito") or "Aguardando confluencia")
        self._conf_verd.configure(
            text=veredito,
            text_color=GREEN if "confirmada" in veredito else YELLOW)