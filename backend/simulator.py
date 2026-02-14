class SimulationEngine:
    def __init__(self, initial_balance=1000):
        self.initial_balance = initial_balance
        self.usdt = initial_balance
        self.btc = 0
        self.trades = []
        self.profit = 0

    def buy(self, price, amount_usdt):
        if self.usdt >= amount_usdt:
            btc_bought = amount_usdt / price
            self.usdt -= amount_usdt
            self.btc += btc_bought
            self.trades.append(("BUY", price))

    def sell(self, price):
        if self.btc > 0:
            usdt_received = self.btc * price
            self.usdt += usdt_received
            self.trades.append(("SELL", price))
            self.btc = 0

    def calculate_profit(self, current_price):
        total_value = self.usdt + (self.btc * current_price)
        self.profit = total_value - self.initial_balance
        return self.profit
