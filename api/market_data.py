#preço em tempo real, histórico, websocket

def pegar_preco_atual(client, simbolo):
    ticker = client.get_symbol_ticker(symbol=simbolo)
    return float(ticker["price"])
