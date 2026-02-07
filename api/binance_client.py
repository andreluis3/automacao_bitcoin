import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

class BinanceClient:
    def __init__(self):
        self.client = Client(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET")
        )

    def preco_atual(self, simbolo):
        ticker = self.client.get_symbol_ticker(symbol=simbolo)
        return float(ticker["price"])

    def comprar_market(self, simbolo, quantidade):
        return self.client.order_market_buy(
            symbol=simbolo,
            quantity=quantidade
        )

    def vender_market(self, simbolo, quantidade):
        return self.client.order_market_sell(
            symbol=simbolo,
            quantity=quantidade
        )
