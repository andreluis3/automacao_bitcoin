class SimulationEngine:
    def __init__(self):
        self.initial_balance_brl = 0.0
        self.balance_brl = 0.0
        self.btc = 0.0
        self.max_buy_brl = 0.0
        self.max_sell_brl = 0.0
        self.trades = []
        self.profit_brl = 0.0

    def configure(self, initial_balance_brl, max_buy_brl, max_sell_brl):
        self.initial_balance_brl = float(initial_balance_brl)
        self.balance_brl = float(initial_balance_brl)
        self.btc = 0.0
        self.max_buy_brl = float(max_buy_brl)
        self.max_sell_brl = float(max_sell_brl)
        self.trades.clear()
        self.profit_brl = 0.0

    def buy(self, btc_price_brl):
        if self.balance_brl <= 0 or btc_price_brl <= 0 or self.max_buy_brl <= 0:
            return 0.0

        amount_brl = min(self.balance_brl, self.max_buy_brl)
        btc_bought = amount_brl / btc_price_brl

        self.balance_brl -= amount_brl
        self.btc += btc_bought
        self.trades.append(("BUY", btc_price_brl, amount_brl, btc_bought))
        return btc_bought

    def sell(self, btc_price_brl):
        if self.btc <= 0 or btc_price_brl <= 0 or self.max_sell_brl <= 0:
            return 0.0

        max_btc_to_sell = self.max_sell_brl / btc_price_brl
        btc_to_sell = min(self.btc, max_btc_to_sell)
        amount_brl = btc_to_sell * btc_price_brl

        self.btc -= btc_to_sell
        self.balance_brl += amount_brl
        self.trades.append(("SELL", btc_price_brl, amount_brl, btc_to_sell))
        return amount_brl

    def calculate_profit(self, btc_price_brl):
        total_value = self.total_balance_brl(btc_price_brl)
        self.profit_brl = total_value - self.initial_balance_brl
        return self.profit_brl

    def total_balance_brl(self, btc_price_brl):
        if btc_price_brl <= 0:
            return self.balance_brl
        return self.balance_brl + (self.btc * btc_price_brl)
