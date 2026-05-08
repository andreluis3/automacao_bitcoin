from api.binance_client import BinanceClient
from api.market_data import MarketDataClient
from interface.main_window import MainWindow
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
                # Chamada segura ao método de cleanup
                on_close_method = getattr(app, '_on_close', None)
                if callable(on_close_method):
                    on_close_method()
                else:
                    # Fallback: tentar shutdown do controller diretamente
                    controller = getattr(app, 'controller', None)
                    if controller and hasattr(controller, 'shutdown'):
                        controller.shutdown()
            except Exception as e:
                print("Erro no shutdown:", e)
            
            try:
                market_data.stop()
            except Exception:
                pass

            try:
                app.destroy()
            except Exception:
                pass
            
            sys.exit()

        app.protocol("WM_DELETE_WINDOW", on_close)

        app.mainloop()

    except Exception as e:
        print("ERRO AO INICIAR A APLICAÇÃO:")
        print(e)
        input("Pressione Enter para sair...")
