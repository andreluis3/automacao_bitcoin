from __future__ import annotations

import logging
import threading
from typing import Any

import requests


class MarketDataClient:
    def __init__(
        self,
        client: Any | None = None,
        base_url: str = "https://api.binance.com",
        symbols: tuple[str, ...] = ("BTCUSDT", "BTCBRL", "USDTBRL"),
        poll_interval_sec: float = 1.0,
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.symbols = tuple(symbols)
        self.poll_interval_sec = max(0.5, float(poll_interval_sec))

        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._latest_prices: dict[str, float] = {}
        self._last_valid_prices: dict[str, float] = {}
        self._latest_klines: dict[tuple[str, str], dict[str, float]] = {}

        self._default_symbol = "BTCUSDT"
        self._consecutive_failures = 0
        self.offline_mode = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="market-data-client", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            had_success = False
            try:
                for symbol in self.symbols:
                    price = self._fetch_price(symbol)
                    if price is None:
                        continue
                    had_success = True
                    with self._lock:
                        self._latest_prices[symbol] = price
                        self._last_valid_prices[symbol] = price

                kline = self._fetch_latest_kline("BTCBRL", "1m")
                if kline is not None:
                    had_success = True
                    with self._lock:
                        self._latest_klines[("BTCBRL", "1m")] = kline
            except Exception:
                had_success = False

            self._handle_cycle_result(had_success)
            self._stop_event.wait(self.poll_interval_sec)

    def _handle_cycle_result(self, had_success: bool) -> None:
        if had_success:
            if self.offline_mode:
                self.logger.info("[SISTEMA] Modo offline desativado")
            self.offline_mode = False
            self._consecutive_failures = 0
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= 5 and not self.offline_mode:
            self.offline_mode = True
            self.logger.warning("[SISTEMA] Modo offline ativado")

    def _fetch_price(self, symbol: str) -> float | None:
        url = f"{self.base_url}/api/v3/ticker/price"
        try:
            resp = requests.get(url, params={"symbol": symbol}, timeout=5)
            resp.raise_for_status()
            payload = resp.json()
            return float(payload["price"])
        except Exception:
            return None

    def _fetch_latest_kline(self, symbol: str, interval: str) -> dict[str, float] | None:
        url = f"{self.base_url}/api/v3/klines"
        try:
            resp = requests.get(
                url,
                params={"symbol": symbol, "interval": interval, "limit": 1},
                timeout=5,
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return None
            row = rows[-1]
            return {
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        except Exception:
            return None

    def get_last_price_safe(self) -> float | None:
        with self._lock:
            return self._last_valid_prices.get(self._default_symbol)

    def get_price_safe(self, symbol: str) -> float | None:
        with self._lock:
            if symbol in self._latest_prices:
                return self._latest_prices[symbol]
            return self._last_valid_prices.get(symbol)

    def pegar_preco_atual(self, simbolo: str) -> float:
        price = self.get_price_safe(simbolo)
        if price is None:
            raise RuntimeError(f"Sem preço disponível para {simbolo}")
        return float(price)

    def get_latest_kline(self, symbol: str = "BTCBRL", interval: str = "1m") -> dict[str, float]:
        key = (symbol, interval)
        with self._lock:
            if key in self._latest_klines:
                return dict(self._latest_klines[key])
        return {"close": 0.0, "volume": 0.0}


MarketData = MarketDataClient
