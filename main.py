from api.binance_client import BinanceClient
from api.market_data import MarketData
from utils.price_buffer import PriceBuffer
from interface.charts import PriceChart

def main():
    # Inicializa cliente da Binance
    binance = BinanceClient()
    client = binance.get_client()

    # Market data usa o client (não API_KEY solta)
    market_data = MarketData(client)

    # Buffer de preços (ex: últimos 60 pontos)
    buffer = PriceBuffer(max_len=60)

    # Gráfico / dashboard
    chart = PriceChart(market_data, buffer)
    chart.run()

if __name__ == "__main__":
    main()
