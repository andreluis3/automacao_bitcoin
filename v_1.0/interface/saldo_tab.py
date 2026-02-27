from __future__ import annotations

import csv
from pathlib import Path

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from interface.theme import APP_BG, CARD_BG, CARD_BORDER, FONT_LABEL, FONT_SECTION, FONT_SMALL, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY


class SaldoTab(ctk.CTkFrame):
    def __init__(self, master, saldo_manager):
        super().__init__(master, fg_color=APP_BG)
        self.saldo_manager = saldo_manager

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=12)
        header.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(header, text="Historico de Saldo", font=FONT_SECTION, text_color=TEXT_PRIMARY).pack(side="left", padx=14, pady=12)
        self.indicador = ctk.CTkLabel(header, text="--", font=FONT_LABEL, text_color=TEXT_SECONDARY)
        self.indicador.pack(side="left", padx=10)

        ctk.CTkButton(
            header,
            text="Exportar CSV",
            command=self._exportar_csv,
            height=34,
            fg_color="#1D4ED8",
            hover_color="#2563EB",
            font=FONT_SMALL,
        ).pack(side="right", padx=14)

        self.grid_text = ctk.CTkTextbox(
            self,
            height=220,
            fg_color=CARD_BG,
            border_width=1,
            border_color=CARD_BORDER,
            text_color=TEXT_PRIMARY,
            font=(FONT_SMALL[0], 13),
        )
        self.grid_text.pack(fill="x", padx=16, pady=(0, 8))

        chart_card = ctk.CTkFrame(self, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=12)
        chart_card.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.fig, self.ax = plt.subplots(figsize=(9, 4))
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_facecolor(APP_BG)
        self.ax.grid(color=CARD_BORDER, alpha=0.3)
        self.ax.tick_params(colors=TEXT_SECONDARY)

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def refresh(self):
        rows = self.saldo_manager.listar_saldos()
        self._render_table(rows)
        self._render_chart(rows)

    def _render_table(self, rows: list[dict]):
        self.grid_text.configure(state="normal")
        self.grid_text.delete("1.0", "end")

        header = "Data | Saldo Inicial | Saldo Final | Lucro Dia | % Dia | Drawdown | Trades | Win Rate\n"
        self.grid_text.insert("end", header)
        self.grid_text.insert("end", "-" * 112 + "\n")

        for r in rows[-120:]:
            linha = (
                f"{r.get('data','-')} | R${float(r.get('saldo_inicial') or 0):,.2f} | "
                f"R${float(r.get('saldo_final') or 0):,.2f} | R${float(r.get('lucro_dia') or 0):,.2f} | "
                f"{float(r.get('percentual_dia') or 0):+.2f}% | {float(r.get('drawdown_dia') or 0):.2f}% | "
                f"{int(r.get('total_trades') or 0)} | {float(r.get('win_rate') or 0):.2f}%\n"
            )
            self.grid_text.insert("end", linha)

        self.grid_text.configure(state="disabled")

        if len(rows) >= 2:
            hoje = float(rows[-1].get("saldo_final") or 0.0)
            ontem = float(rows[-2].get("saldo_final") or 0.0)
            up = hoje >= ontem
            self.indicador.configure(text=("Saldo > ontem" if up else "Saldo < ontem"), text_color=(GREEN if up else RED))
        elif rows:
            self.indicador.configure(text="Primeiro registro", text_color=TEXT_SECONDARY)
        else:
            self.indicador.configure(text="Sem dados", text_color=TEXT_SECONDARY)

    def _render_chart(self, rows: list[dict]):
        self.ax.clear()
        self.ax.set_facecolor(APP_BG)
        self.ax.grid(color=CARD_BORDER, alpha=0.3)
        self.ax.tick_params(colors=TEXT_SECONDARY)

        if rows:
            x = np.arange(len(rows))
            y = np.array([float(r.get("saldo_final") or 0.0) for r in rows])
            self.ax.plot(x, y, color="#F59E0B", linewidth=2.0)
            self.ax.set_title("Curva de Capital Acumulada", color=TEXT_PRIMARY)
            self.ax.set_ylabel("Saldo (R$)", color=TEXT_SECONDARY)
        self.canvas.draw_idle()

    def _exportar_csv(self):
        rows = self.saldo_manager.listar_saldos()
        if not rows:
            return
        out_dir = Path("v_1.0/log")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "saldo_historico.csv"

        fields = [
            "data",
            "saldo_inicial",
            "saldo_final",
            "lucro_dia",
            "percentual_dia",
            "drawdown_dia",
            "total_trades",
            "win_rate",
            "criado_em",
        ]
        with out_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
