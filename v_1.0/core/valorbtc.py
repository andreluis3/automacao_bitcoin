from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime
from typing import Callable

import requests

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover
    websocket = None


class BTCPriceFeed:
    def __init__(
        self,
        symbol: str = "BTCBRL",
        rest_interval_sec: float = 1.0,
        prefer_websocket: bool = True,
        simulation_fallback: bool = False,
        callback_on_tick: Callable[[float, float], None] | None = None,
        callback_on_log: Callable[[str], None] | None = None,
    ):
        self.symbol = symbol.upper()
        self.rest_interval_sec = max(0.5, float(rest_interval_sec))
        self.prefer_websocket = bool(prefer_websocket)
        self.simulation_fallback = bool(simulation_fallback)
        self.callback_on_tick = callback_on_tick
        self.callback_on_log = callback_on_log

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_price = 0.0
        self._last_volume = 0.0
        self._last_tick_ts = 0.0
        self._ws_app = None
        self._started_ts = 0.0

    def _log(self, msg: str) -> None:
        if self.callback_on_log:
            self.callback_on_log(msg)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        print("Feed BTC iniciado")
        self._log("Feed BTC iniciado")
        self._stop_event.clear()
        self._started_ts = time.time()
        self._thread = threading.Thread(target=self._run, name="btc-price-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            if self._ws_app is not None:
                self._ws_app.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def reconnect(self) -> None:
        self._log("Sem dados. Reconectando...")
        print("Sem dados. Reconectando...")
        try:
            if self._ws_app is not None:
                self._ws_app.close()
        except Exception:
            pass

    def get_last_price(self) -> float | None:
        with self._lock:
            return self._last_price if self._last_price > 0 else None

    def _emit_tick(self, price: float, volume: float) -> None:
        with self._lock:
            self._last_price = float(price)
            self._last_volume = float(volume)
            self._last_tick_ts = time.time()
        print(f"Novo preço BTC: {price}")
        self._log(f"Novo tick BTC | preço={price:.2f} volume={volume:.6f}")
        if self.callback_on_tick:
            self.callback_on_tick(float(price), float(volume))

    def _run(self) -> None:
        # Prioriza websocket; se falhar, cai para REST polling.
        while not self._stop_event.is_set():
            if self.prefer_websocket and websocket is not None:
                self._run_websocket_once()
            else:
                self._run_rest_once()

            if self._stop_event.is_set():
                break

            last_tick_ts = 0.0
            with self._lock:
                last_tick_ts = self._last_tick_ts
            now_ts = time.time()
            stale_no_tick = last_tick_ts <= 0 and self._started_ts > 0 and (now_ts - self._started_ts) > 30.0
            stale_with_tick = last_tick_ts > 0 and (now_ts - last_tick_ts) > 30.0
            if stale_no_tick or stale_with_tick:
                self.reconnect()

            time.sleep(0.4)

    def _run_websocket_once(self) -> None:
        stream = self.symbol.lower() + "@trade"
        url = f"wss://stream.binance.com:9443/ws/{stream}"
        self._log(f"Conectando websocket: {url}")

        def _on_message(_ws, message: str) -> None:
            try:
                payload = json.loads(message)
                price = float(payload.get("p", 0.0))
                volume = float(payload.get("q", 0.0))
                if price > 0:
                    self._emit_tick(price, volume)
            except Exception:
                pass

        def _on_open(_ws) -> None:
            self._log("WebSocket conectado")

        def _on_close(_ws, _code, _reason) -> None:
            self._log("WebSocket desconectado")

        def _on_error(_ws, err) -> None:
            self._log(f"Erro WebSocket: {err}")

        try:
            self._ws_app = websocket.WebSocketApp(
                url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            self._ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as exc:
            self._log(f"Falha websocket, fallback REST: {exc}")
            self._run_rest_once()
        finally:
            self._ws_app = None

    def _run_rest_once(self) -> None:
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            resp = requests.get(url, params={"symbol": self.symbol}, timeout=5)
            resp.raise_for_status()
            payload = resp.json()
            price = float(payload.get("lastPrice", 0.0))
            volume = float(payload.get("volume", 0.0))
            if price > 0:
                self._emit_tick(price, volume)
                self._log("REST conectado")
            else:
                self._maybe_simulate_tick()
        except Exception:
            self._log("REST desconectado")
            self._maybe_simulate_tick()
        time.sleep(self.rest_interval_sec)

    def _maybe_simulate_tick(self) -> None:
        if not self.simulation_fallback:
            return
        base = self.get_last_price() or 300000.0
        drift = random.uniform(-0.0012, 0.0012)
        price = max(10000.0, base * (1.0 + drift))
        volume = random.uniform(0.05, 0.9)
        self._emit_tick(price, volume)
        self._log("Tick simulado gerado (fallback)")
