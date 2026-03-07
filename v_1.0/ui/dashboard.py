from __future__ import annotations

from ui.cards import create_card


class DashboardCards:
    def __init__(self, parent):
        self.parent = parent
        self.cards = {}

    def build(self):
        self.cards["btc_price"] = create_card(self.parent, "BTC PRICE", "$0.00", 0, 0)
        self.cards["saldo"] = create_card(self.parent, "SALDO", "R$0.00", 0, 1)
        self.cards["drawdown"] = create_card(self.parent, "DRAWDOWN", "0.00%", 0, 2)
        self.cards["estrategia"] = create_card(self.parent, "ESTRATEGIA", "AUTO", 0, 3)
        self.cards["taxas"] = create_card(self.parent, "TAXAS PAGAS", "R$0.00", 1, 0)
        self.cards["posicao"] = create_card(self.parent, "STATUS POSICAO", "NONE", 1, 1)
        return self.cards
