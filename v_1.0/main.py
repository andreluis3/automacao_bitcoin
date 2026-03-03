from api.binance_client import BinanceClient
from api.market_data import MarketDataClient
from interface.main_window import MainWindow
import sys

import sys

if __name__ == "__main__":
    try:
        client = None
        try:
            binance = BinanceClient()
            client = binance.get_client()
        except Exception as exc:
            print("Falha ao iniciar cliente Binance:", exc)

        market_data = MarketDataClient(client=client)
        market_data.start()

        app = MainWindow(market_data)

        def on_close():
            try:
                app.shutdown()
            except Exception as e:
                print("Erro no shutdown:", e)
            try:
                market_data.stop()
            except Exception:
                pass

            app.destroy()  # destroy já encerra a janela
            sys.exit()

        app.protocol("WM_DELETE_WINDOW", on_close)

        app.mainloop()

    except Exception as e:
        print("ERRO AO INICIAR A APLICAÇÃO:")
        print(e)
        input("Pressione Enter para sair...")
