# main.py

from api.market_data import MarketData
from utils.price_buffer import PriceBuffer
from interface.charts import PriceChart

API_KEY = "SUA_API_KEY"
API_SECRET = "SEU_API_SECRET"

def main():
    market_data = MarketData(API_KEY, API_SECRET)
    buffer = PriceBuffer(max_len=60)

    chart = PriceChart(market_data, buffer)
    chart.run()

if __name__ == "__main__":
    main()
