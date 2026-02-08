import matplotlib.pyplot as plt
import time

class PriceChart:
    def __init__(self, market_data, buffer, symbol="BTCUSDT"):
        self.market_data = market_data
        self.buffer = buffer
        self.symbol = symbol

        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [])

        self.ax.set_title("Bitcoin Price (BTC/USDT)")
        self.ax.set_xlabel("Tempo")
        self.ax.set_ylabel("Preço (USDT)")
        self.ax.grid(True)

    def run(self):
        plt.ion()  # modo interativo
        plt.show()

        while True:
            try:
                preco = self.market_data.pegar_preco_atual(self.symbol)
                print("Preço capturado:", preco)

                self.buffer.add(preco)
                dados = self.buffer.get_all()

                self.line.set_data(range(len(dados)), dados)
                self.ax.relim()
                self.ax.autoscale_view()

                plt.pause(1)  # atualiza a cada 1 segundo

            except Exception as e:
                print("Erro ao atualizar gráfico:", e)
                time.sleep(2)
