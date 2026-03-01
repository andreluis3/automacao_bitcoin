from __future__ import annotations

from datetime import datetime


class UIBridge:
    def __init__(self, app):
        self.app = app

    def update_dashboard(self, snapshot: dict) -> None:
        price = float(snapshot.get("price_usdt", 0.0))
        variation = float(snapshot.get("variation_pct", 0.0))
        equity = float(snapshot.get("equity_brl", 0.0))
        drawdown = float(snapshot.get("current_drawdown_pct", 0.0))
        state = str(snapshot.get("state", "parado"))
        mode = str(snapshot.get("mode", "simulacao")).upper()

        arrow = "↑" if variation > 0 else "↓" if variation < 0 else ""
        sign = "+" if variation > 0 else ""
        var_txt = f" {arrow} {sign}{variation:.2f}%" if arrow else ""
        header = (
            f"BTC/USDT: ${price:,.2f}{var_txt}  Modo: {mode}  "
            f"Saldo R$: {equity:,.2f}  Saldo BTC: 0.00000000  Taxas: 0.00  Drawdown Atual: {drawdown:.2f}%"
        )

        color = "#e5e7eb"
        if variation > 0:
            color = "#22c55e"
        elif variation < 0:
            color = "#ef4444"

        self.app.preco_label.configure(text=header, text_color=color)

        lucro = equity - float(self.app.controller.initial_equity_reference())
        lucro_color = "#22c55e" if lucro > 0 else "#ef4444" if lucro < 0 else "#e5e7eb"
        self.app.card_lucro_value.configure(text=f"R$ {lucro:,.2f}", text_color=lucro_color)
        self.app.card_saldo_value.configure(text=f"R$ {equity:,.2f}")
        self.app.card_drawdown_value.configure(text=f"{drawdown:.2f}%")
        self.app.drawdown_progress.set(min(drawdown / 100.0, 1.0))

        self._update_status_badge(state)

    def _update_status_badge(self, state: str) -> None:
        if state == "real":
            led_color = "#22c55e"
            badge = "REAL RODANDO"
        elif state == "simulando":
            led_color = "#3b82f6"
            badge = "SIMULAÇÃO RODANDO"
        else:
            led_color = "#6b7280"
            badge = "PARADO"

        self.app.led_status.configure(text_color=led_color)
        self.app.badge_status.configure(text=badge)

    def log_message(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        box = self.app.console_box
        box.configure(state="normal")
        box.insert("end", line)
        box.see("end")
        box.configure(state="disabled")
