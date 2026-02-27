from api.binance_client import BinanceClient

binance = BinanceClient()

preco = binance.preco_atual("BTCBRL")
print("Preço atual:", preco)
