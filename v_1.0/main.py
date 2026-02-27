from api.binance_client import BinanceClient
from api.market_data import MarketData
from interface.main_window import MainWindow
import sys

import sys

if __name__ == "__main__":
    try:
        binance = BinanceClient()
        client = binance.get_client()
        market_data = MarketData(client)

        app = MainWindow(market_data)

        def on_close():
            try:
                app.shutdown()
            except Exception as e:
                print("Erro no shutdown:", e)

            app.destroy()  # destroy já encerra a janela
            sys.exit()

        app.protocol("WM_DELETE_WINDOW", on_close)

        app.mainloop()

    except Exception as e:
        print("ERRO AO INICIAR A APLICAÇÃO:")
        print(e)
        input("Pressione Enter para sair...")