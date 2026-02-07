import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

class PriceChart:
    def __init__(self, market_data, price_buffer):
        self.market_data = market_data
        self.price_buffer = price_buffer

        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [], linewidth=2)

        self.ax.set_title("Bitcoin Price (BTC/USDT)")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Price (USDT)")
        self.ax.grid(True)

    def update(self, frame):
        price = self.market_data.get_btc_price()
        timestamp = self.market_data.get_timestamp()

        self.price_buffer.add(price, timestamp)

        x, y = self.price_buffer.get_data()

        self.line.set_data(range(len(y)), y)
        self.ax.set_xlim(0, len(y))
        self.ax.set_ylim(min(y) * 0.999, max(y) * 1.001)

        return self.line,

    def run(self):
        animation = FuncAnimation(
            self.fig,
            self.update,
            interval=5000  # atualiza a cada 5 segundos
        )
        plt.show()
