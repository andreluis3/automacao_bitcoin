from api.binance_client import BinanceClient
from api.market_data import MarketData
from interface.main_window import MainWindow


if __name__ == "__main__":
    from api.binance_client import BinanceClient
    from api.market_data import MarketData

    binance = BinanceClient()
    client = binance.get_client()
    market_data = MarketData(client)

    app = MainWindow(market_data)
    app.mainloop()

