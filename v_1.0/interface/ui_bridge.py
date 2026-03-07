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
        lucro_hoje = float(snapshot.get("lucro_hoje_brl", 0.0))
        safe_reserve = float(snapshot.get("safe_reserve_brl", 0.0))
        exposicao_brl = float(snapshot.get("current_exposure_brl", 0.0))
        exposicao_pct = float(snapshot.get("current_exposure_pct", 0.0))
        profit_factor = float(snapshot.get("profit_factor", 0.0))
        patrimonio_protegido = float(snapshot.get("patrimonio_protegido_brl", 0.0))
        pf_warning = bool(snapshot.get("profit_factor_warning", False))
        state = str(snapshot.get("state", "parado"))
        mode = str(snapshot.get("mode", "simulacao")).upper()
        strategy_mode_selected = str(snapshot.get("strategy_mode_selected", "auto")).upper()
        strategy_mode_active = str(snapshot.get("strategy_mode_active", "lateral")).upper()

        arrow = "↑" if variation > 0 else "↓" if variation < 0 else ""
        sign = "+" if variation > 0 else ""
        var_txt = f" {arrow} {sign}{variation:.2f}%" if arrow else ""
        header = (
            f"BTC/USDT: ${price:,.2f}{var_txt}  Modo: {mode}  "
            f"Estrategia: {strategy_mode_selected}/{strategy_mode_active}  "
            f"Equity R$: {equity:,.2f}  Drawdown Atual: {drawdown:.2f}%"
        )

        color = "#e5e7eb"
        if variation > 0:
            color = "#22c55e"
        elif variation < 0:
            color = "#ef4444"

        self.app.preco_label.configure(text=header, text_color=color)

        lucro_color = "#22c55e" if lucro_hoje > 0 else "#ef4444" if lucro_hoje < 0 else "#e5e7eb"
        self.app.card_lucro_value.configure(text=f"R$ {lucro_hoje:,.2f}", text_color=lucro_color)
        self.app.card_equity_value.configure(text=f"R$ {equity:,.2f}")
        self.app.card_reserva_value.configure(text=f"R$ {safe_reserve:,.2f}")
        self.app.card_exposicao_value.configure(text=f"R$ {exposicao_brl:,.2f} ({exposicao_pct:.2f}%)")
        self.app.card_profit_factor_value.configure(text=f"{profit_factor:.2f}")
        self.app.card_patrimonio_protegido_value.configure(text=f"R$ {patrimonio_protegido:,.2f}")
        self.app.card_drawdown_value.configure(text=f"{drawdown:.2f}%")
        self.app.drawdown_progress.set(min(drawdown / 100.0, 1.0))
        if pf_warning:
            self.app.card_alerta_value.configure(text="Estratégia com baixa expectativa matemática")
        else:
            self.app.card_alerta_value.configure(text="")

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
