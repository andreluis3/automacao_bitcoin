from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


@dataclass
class SimPosition:
    entry_price: float
    quantity: float
    invested_brl: float
    stop_loss: float
    highest_price: float
    breakeven_armed: bool = False
    stop_mode: str = "SL"


class StrategyEngine:
    def __init__(self, hysteresis_pct: float = 0.005):
        self.hysteresis_pct = float(hysteresis_pct)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema9"] = out["close"].ewm(span=9, adjust=False).mean()
        out["sma21"] = out["close"].rolling(window=21).mean()

        delta = out["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        out["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        out["volume_mean"] = out["volume"].rolling(window=20).mean()

        bb_mid = out["close"].rolling(window=20).mean()
        bb_std = out["close"].rolling(window=20).std(ddof=0)
        bb_upper = bb_mid + (2.0 * bb_std)
        bb_lower = bb_mid - (2.0 * bb_std)
        out["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0.0, np.nan)
        out["bb_width_mean"] = out["bb_width"].rolling(window=20).mean()
        return out

    def should_buy(self, row: pd.Series) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        cond_ema_sma = float(row["ema9"]) > (float(row["sma21"]) * (1.0 + self.hysteresis_pct))
        cond_pullback = float(row["close"]) < (float(row["sma21"]) * 0.98)
        cond_rsi = float(row["rsi"]) < 30.0
        cond_volume = float(row["volume"]) > (float(row["volume_mean"]) * 1.2)
        cond_volatility = float(row["bb_width"]) > float(row["bb_width_mean"])

        if cond_ema_sma:
            reasons.append("EMA9 > SMA21 + histerese(0.5%)")
        if cond_pullback:
            reasons.append("Preco < SMA21 * 0.98")
        if cond_rsi:
            reasons.append("RSI < 30")
        if cond_volume:
            reasons.append("Volume > media_volume * 1.2")
        if cond_volatility:
            reasons.append("Expansao de volatilidade (BB width)")

        should = cond_ema_sma and cond_pullback and cond_rsi and cond_volume and cond_volatility
        return should, reasons

    def should_sell_by_cross(self, row: pd.Series) -> bool:
        return float(row["ema9"]) < float(row["sma21"])


class RiskManager:
    def __init__(
        self,
        percentual_por_trade: float = 0.10,
        stop_loss_percent: float = 0.02,
        trailing_percent: float = 0.015,
        breakeven_percent: float = 0.01,
        fee_rate: float = 0.001,
    ):
        self.percentual_por_trade = max(0.0, float(percentual_por_trade))
        self.stop_loss_percent = max(0.0, float(stop_loss_percent))
        self.trailing_percent = max(0.0, float(trailing_percent))
        self.breakeven_percent = max(0.0, float(breakeven_percent))
        self.fee_rate = max(0.0, float(fee_rate))

    def quote_for_trade(self, saldo_brl: float) -> float:
        quote = max(0.0, saldo_brl * self.percentual_por_trade)
        return min(quote, max(0.0, saldo_brl))


class PositionManager:
    def __init__(self, saldo_inicial: float):
        self.saldo_brl = max(0.0, float(saldo_inicial))
        self.position: SimPosition | None = None

    def has_position(self) -> bool:
        return self.position is not None

    def open_position(self, price: float, quote_brl: float, risk: RiskManager) -> dict[str, float]:
        if self.position is not None or price <= 0:
            return {"quantity": 0.0, "fee_brl": 0.0}

        quote = min(max(0.0, quote_brl), self.saldo_brl)
        if quote <= 0.0:
            return {"quantity": 0.0, "fee_brl": 0.0}

        fee_brl = quote * risk.fee_rate
        net_quote = max(0.0, quote - fee_brl)
        quantity = net_quote / price if price > 0 else 0.0
        if quantity <= 0.0:
            return {"quantity": 0.0, "fee_brl": 0.0}

        self.saldo_brl = max(0.0, self.saldo_brl - quote)
        self.position = SimPosition(
            entry_price=price,
            quantity=quantity,
            invested_brl=quote,
            stop_loss=price * (1.0 - risk.stop_loss_percent),
            highest_price=price,
        )
        return {"quantity": quantity, "fee_brl": fee_brl}

    def update_dynamic_stops(self, current_price: float, risk: RiskManager) -> None:
        if self.position is None:
            return

        pos = self.position
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        breakeven_trigger = pos.entry_price * (1.0 + risk.breakeven_percent)
        if (not pos.breakeven_armed) and current_price >= breakeven_trigger:
            pos.stop_loss = max(pos.stop_loss, pos.entry_price)
            pos.breakeven_armed = True
            pos.stop_mode = "BREAKEVEN"

        trailing_stop = pos.highest_price * (1.0 - risk.trailing_percent)
        if trailing_stop > pos.stop_loss:
            pos.stop_loss = trailing_stop
            pos.stop_mode = "TRAILING"

    def should_exit_by_stop(self, current_price: float) -> tuple[bool, str]:
        if self.position is None:
            return False, ""
        if current_price <= self.position.stop_loss:
            return True, self.position.stop_mode
        return False, ""

    def close_position(self, price: float, risk: RiskManager) -> dict[str, float]:
        if self.position is None or price <= 0:
            return {"amount_brl": 0.0, "fee_brl": 0.0, "pnl_brl": 0.0}

        pos = self.position
        gross_brl = pos.quantity * price
        fee_brl = gross_brl * risk.fee_rate
        net_brl = max(0.0, gross_brl - fee_brl)
        pnl_brl = net_brl - pos.invested_brl

        self.saldo_brl = max(0.0, self.saldo_brl + net_brl)
        self.position = None
        return {"amount_brl": net_brl, "fee_brl": fee_brl, "pnl_brl": pnl_brl}


class PerformanceTracker:
    def __init__(self, saldo_inicial: float):
        self.saldo_inicial = max(0.0, float(saldo_inicial))
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def register_trade(self, pnl_brl: float) -> None:
        self.total_trades += 1
        if pnl_brl > 0:
            self.wins += 1
        else:
            self.losses += 1

    def snapshot(self, saldo_final: float) -> dict[str, float]:
        lucro_pct = 0.0
        if self.saldo_inicial > 0:
            lucro_pct = ((saldo_final - self.saldo_inicial) / self.saldo_inicial) * 100.0
        win_rate = (self.wins / self.total_trades * 100.0) if self.total_trades > 0 else 0.0
        return {
            "saldo_inicial": self.saldo_inicial,
            "saldo_final": saldo_final,
            "lucro_pct": lucro_pct,
            "total_trades": float(self.total_trades),
            "win_rate": win_rate,
        }


class SimulationEngine:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "15m",
        limit: int = 200,
        saldo_inicial: float = 10000.0,
        percentual_por_trade: float = 0.10,
        stop_loss_percent: float = 0.02,
        trailing_percent: float = 0.015,
        breakeven_percent: float = 0.01,
        log_path: str | None = None,
    ):
        self.symbol = symbol.upper().strip()
        self.interval = interval if interval in {"15m", "1h"} else "15m"
        self.limit = max(50, min(int(limit), 1000))
        self.log_file = Path(log_path) if log_path else Path(__file__).resolve().parent / "simulation_log.txt"

        self.strategy = StrategyEngine(hysteresis_pct=0.005)
        self.risk = RiskManager(
            percentual_por_trade=percentual_por_trade,
            stop_loss_percent=stop_loss_percent,
            trailing_percent=trailing_percent,
            breakeven_percent=breakeven_percent,
            fee_rate=0.001,
        )
        self.positions = PositionManager(saldo_inicial=saldo_inicial)
        self.performance = PerformanceTracker(saldo_inicial=saldo_inicial)

    def run(self) -> dict[str, Any]:
        print("[SIMULATION START]")
        self._ensure_log_header()

        try:
            candles = self._fetch_klines()
            df = self._prepare_dataframe(candles)
            df = self.strategy.add_indicators(df)
            df = df.dropna(subset=["ema9", "sma21", "rsi", "volume_mean", "bb_width", "bb_width_mean"]).reset_index(drop=True)
        except Exception as exc:
            print(f"[ERROR] {exc}")
            return {"ok": False, "error": str(exc)}

        for _, row in df.iterrows():
            price = float(row["close"])
            self._print_candle(row)

            if self.positions.has_position():
                self.positions.update_dynamic_stops(price, self.risk)
                stop_hit, stop_reason = self.positions.should_exit_by_stop(price)
                if stop_hit:
                    self._execute_sell(price=price, reason=stop_reason, when=row["open_time"])
                    continue
                if self.strategy.should_sell_by_cross(row):
                    self._execute_sell(price=price, reason="CRUZAMENTO_CONTRARIO", when=row["open_time"])
                    continue
                continue

            should_buy, reasons = self.strategy.should_buy(row)
            if should_buy:
                self._execute_buy(price=price, reasons=reasons, when=row["open_time"])

        if self.positions.has_position():
            last = df.iloc[-1]
            self._execute_sell(price=float(last["close"]), reason="ENCERRAMENTO_SIMULACAO", when=last["open_time"])

        summary = self.performance.snapshot(self.positions.saldo_brl)
        print("[SIMULATION END]")
        print(f"Saldo inicial: {summary['saldo_inicial']:.2f}")
        print(f"Saldo final: {summary['saldo_final']:.2f}")
        print(f"Lucro %: {summary['lucro_pct']:.2f}%")
        print(f"Total trades: {int(summary['total_trades'])}")
        print(f"Win rate: {summary['win_rate']:.2f}%")
        return {"ok": True, **summary}

    def _execute_buy(self, price: float, reasons: list[str], when: datetime) -> None:
        quote = self.risk.quote_for_trade(self.positions.saldo_brl)
        opened = self.positions.open_position(price=price, quote_brl=quote, risk=self.risk)
        qty = float(opened.get("quantity", 0.0))
        if qty <= 0.0:
            return

        pos = self.positions.position
        if pos is None:
            return

        print("[BUY]")
        print(f"Preco: {price:.2f}")
        print(f"Quantidade: {qty:.8f}")
        print(f"Saldo restante: {self.positions.saldo_brl:.2f}")
        print(f"Motivo da entrada: {', '.join(reasons)}")
        self._write_log(
            when=when,
            operation_type="BUY",
            price=price,
            quantity=qty,
            stop_atual=pos.stop_loss,
            saldo_apos=self.positions.saldo_brl,
        )

    def _execute_sell(self, price: float, reason: str, when: datetime) -> None:
        pos = self.positions.position
        if pos is None:
            return
        qty = pos.quantity
        stop = pos.stop_loss

        closed = self.positions.close_position(price=price, risk=self.risk)
        pnl = float(closed.get("pnl_brl", 0.0))
        self.performance.register_trade(pnl)

        print("[SELL]")
        print(f"Preco: {price:.2f}")
        print(f"Lucro/Prejuizo: {pnl:+.2f}")
        print(f"Novo saldo: {self.positions.saldo_brl:.2f}")
        print(f"Motivo da saida: {reason}")
        self._write_log(
            when=when,
            operation_type=f"SELL({reason})",
            price=price,
            quantity=qty,
            stop_atual=stop,
            saldo_apos=self.positions.saldo_brl,
        )

    def _print_candle(self, row: pd.Series) -> None:
        pos_status = "SIM" if self.positions.has_position() else "NAO"
        print(
            "[CANDLE] "
            f"Preco={float(row['close']):.2f} | EMA={float(row['ema9']):.2f} | SMA={float(row['sma21']):.2f} | "
            f"RSI={float(row['rsi']):.2f} | Volume={float(row['volume']):.2f} | "
            f"Saldo={self.positions.saldo_brl:.2f} | EmPosicao={pos_status}"
        )

    def _fetch_klines(self) -> list[list[Any]]:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": self.symbol, "interval": self.interval, "limit": self.limit}
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"falha ao consultar Binance: {exc}") from exc

        if not isinstance(data, list) or not data:
            raise RuntimeError("resposta vazia da Binance")
        return data

    def _prepare_dataframe(self, candles: list[list[Any]]) -> pd.DataFrame:
        columns = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        df = pd.DataFrame(candles, columns=columns)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["close", "volume"]).reset_index(drop=True)

    def _ensure_log_header(self) -> None:
        if self.log_file.exists() and self.log_file.stat().st_size > 0:
            return
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write("data_hora | tipo_operacao | preco | quantidade | stop_atual | saldo_apos\n")

    def _write_log(
        self,
        when: datetime,
        operation_type: str,
        price: float,
        quantity: float,
        stop_atual: float,
        saldo_apos: float,
    ) -> None:
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write(
                f"{when.isoformat()} | {operation_type} | {price:.2f} | {quantity:.8f} | "
                f"{stop_atual:.2f} | {saldo_apos:.2f}\n"
            )
