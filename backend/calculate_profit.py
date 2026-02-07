def calcular_lucro(entry_price, exit_price, quantidade, taxa):
    valor_compra = entry_price * quantidade
    valor_venda = exit_price * quantidade

    lucro = valor_venda - valor_compra - taxa
    profit_percent = (lucro / valor_compra) * 100

    return round(lucro, 2), round(profit_percent, 2)
