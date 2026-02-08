class MarketData:
    def __init__(self, client):
        self.client = client
        print("MarketData carregado, pegando valor atual ...")

    def pegar_preco_atual(self, simbolo: str) -> float: 
        ticker = self.client.get_symbol_ticker(symbol=simbolo)
        return float(ticker["price"])
