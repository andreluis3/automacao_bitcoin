from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


@dataclass
class SimulationConfig:
    symbol: str = "BTCUSDT"
    interval: str = "15m"
    limit: int = 500
    capital_inicial: float = 10000.0
    slippage_pct: float = 0.0002
    taxa_maker_pct: float = 0.0002
    taxa_taker_pct: float = 0.0004
    latencia_min_ms: int = 80
    latencia_max_ms: int = 240
    aplicar_sleep_latencia: bool = True
    log_path: str = "simulation_log.txt"


@dataclass
class Position:
    opened_at: datetime
    entry_price: float
    qty_btc: float
    invested_brl: float
    entry_fee_brl: float


class SimulationEngine:
    """
    Engine de simulacao simplificado:
    - Estrategia unica: EMA7 x SMA40
    - Entrada por cruzamento real em candles fechados (-3 e -2)
    - Saida por perda de EMA7, cruzamento contrario ou trailing EMA7
    """

    def __init__(self, config: SimulationConfig | None = None):
        self.cfg = config or SimulationConfig()
        self.position: Position | None = None

        self.capital = float(self.cfg.capital_inicial)
        self.initial_capital = float(self.cfg.capital_inicial)
        self.equity_peak = float(self.cfg.capital_inicial)
        self.max_drawdown_pct = 0.0

        self.total_cross = 0
        self.cross_filtrados = 0
        self.cross_executados = 0
        self.trades_lucrativos = 0
        self.trades_prejuizo = 0

        self.equity_history: list[float] = [self.capital]
        self.benchmark_history: list[float] = []
        self.trades: list[dict[str, Any]] = []
        self.trade_returns: list[float] = []

        self.log_file = Path(self.cfg.log_path)
        self._ensure_log_header()

    def rodar(self) -> dict[str, Any]:
        print ("simulação inciada")
        try:
            candles = self._baixar_dados_binance()
            if candles.empty:
                raise RuntimeError("Sem dados para simulação.")
            candles = self._preparar_indicadores(candles)
            if len(candles) < 45:
                raise RuntimeError("Quantidade insuficiente de candles para EMA7/SMA40.")
        except Exception as exc:
            print(f"[ERRO] {exc}")
            return {"ok": False, "error": str(exc)}

        # A cada iteração, o candle idx é tratado como em formação.
        # Sinais usam somente candles fechados idx-2 e idx-1.
        for idx in range(2, len(candles)):
            print(f"Processando candle {self.current_index}")
            now = candles.iloc[idx]["open_time"]
            c3 = candles.iloc[idx - 2]  # -3
            c2 = candles.iloc[idx - 1]  # -2 (último fechado)

            close2 = float(c2["close"])
            low2 = float(c2["low"])
            ema2 = float(c2["ema7"])
            sma2 = float(c2["sma40"])
            ema3 = float(c3["ema7"])
            sma3 = float(c3["sma40"])

            self.benchmark_history.append(close2)
            self._update_drawdown(self._equity_mark_to_market(close2))

            if self.position is not None:
                if self._check_exit_by_rules(now=now, c2=c2, c3=c3):
                    self.equity_history.append(self.capital)
                else:
                    self.equity_history.append(self._equity_mark_to_market(close2))
                continue

            crossed_up = ema3 <= sma3 and ema2 > sma2
            if not crossed_up:
                self.equity_history.append(self.capital)
                continue

            self.total_cross += 1

            filtro_sma40_sobe = float(c2["sma40"]) > float(c3["sma40"])
            filtro_low_acima_ema = low2 > ema2
            if not (filtro_sma40_sobe and filtro_low_acima_ema):
                self.cross_filtrados += 1
                self._log_info(
                    now=now,
                    msg=(
                        f"CROSS FILTRADO | sma40_sobe={filtro_sma40_sobe} "
                        f"| low2={low2:.2f} ema2={ema2:.2f}"
                    ),
                )
                self.equity_history.append(self.capital)
                continue

            quote = self._compute_quote_from_distance(close=close2, sma40=sma2)
            if quote <= 0:
                self.cross_filtrados += 1
                self.equity_history.append(self.capital)
                continue

            self._open_position(now=now, reference_price=close2, quote_brl=quote)
            self.cross_executados += 1
            self.equity_history.append(self._equity_mark_to_market(close2))

        if self.position is not None and len(candles) > 0:
            last = candles.iloc[-1]
            self._close_position(
                when=last["close_time"],
                exit_ref_price=float(last["close"]),
                reason="encerramento_simulacao",
                fee_type="taker",
            )
            self.equity_history.append(self.capital)

        stats = self._build_stats()
        self._print_report(stats)
        return {"ok": True, **stats}

    def _check_exit_by_rules(self, now: datetime, c2: pd.Series, c3: pd.Series) -> bool:
        if self.position is None:
            return False

        low2 = float(c2["low"])
        ema2 = float(c2["ema7"])
        sma2 = float(c2["sma40"])
        ema3 = float(c3["ema7"])
        sma3 = float(c3["sma40"])

        # 1) mínima fechada abaixo da EMA7
        if low2 < ema2:
            self._close_position(
                when=now,
                exit_ref_price=float(c2["close"]),
                reason="low_abaixo_ema7",
                fee_type="taker",
            )
            return True

        # 2) cruzamento contrário EMA7 abaixo da SMA40
        crossed_down = ema3 >= sma3 and ema2 < sma2
        if crossed_down:
            self._close_position(
                when=now,
                exit_ref_price=float(c2["close"]),
                reason="cross_down_ema7_sma40",
                fee_type="taker",
            )
            return True

        # 3) trailing pela EMA7
        trailing_stop = ema2 * 0.995
        if low2 <= trailing_stop:
            self._close_position(
                when=now,
                exit_ref_price=trailing_stop,
                reason="trailing_ema7",
                fee_type="maker",
            )
            return True

        return False

    def _compute_quote_from_distance(self, close: float, sma40: float) -> float:
        if self.capital <= 0 or sma40 <= 0:
            return 0.0
        dist = (close - sma40) / sma40
        if -0.02 <= dist <= 0.0:
            pct = 0.15
        elif -0.04 <= dist < -0.02:
            pct = 0.25
        elif dist < -0.04:
            pct = 0.35
        else:
            pct = 0.15
        pct = min(0.35, max(0.0, pct))
        return min(self.capital, self.capital * pct)

    def _open_position(self, now: datetime, reference_price: float, quote_brl: float) -> None:
        if self.position is not None or reference_price <= 0 or quote_brl <= 0:
            return

        self._simulate_latency()
        entry_exec = self._apply_slippage(reference_price, side="buy")
        entry_fee = quote_brl * self.cfg.taxa_taker_pct
        qty_btc = max(0.0, (quote_brl - entry_fee) / entry_exec)
        if qty_btc <= 0:
            return

        self.capital = max(0.0, self.capital - quote_brl)
        self.position = Position(
            opened_at=now,
            entry_price=entry_exec,
            qty_btc=qty_btc,
            invested_brl=quote_brl,
            entry_fee_brl=entry_fee,
        )
        self._log_trade(
            when=now,
            tipo="BUY",
            preco=entry_exec,
            quantidade=qty_btc,
            fee=entry_fee,
            pnl_liquido=0.0,
            motivo="cross_up_ema7_sma40",
            saldo_apos=self.capital,
        )

    def _close_position(self, when: datetime, exit_ref_price: float, reason: str, fee_type: str) -> None:
        if self.position is None:
            return

        self._simulate_latency()
        pos = self.position
        exit_exec = self._apply_slippage(exit_ref_price, side="sell")
        fee_rate = self.cfg.taxa_taker_pct if fee_type == "taker" else self.cfg.taxa_maker_pct
        gross = pos.qty_btc * exit_exec
        exit_fee = gross * fee_rate
        net_exit = gross - exit_fee
        self.capital = max(0.0, self.capital + net_exit)

        gross_pnl = gross - pos.invested_brl
        net_pnl = gross_pnl - pos.entry_fee_brl - exit_fee
        ret = (net_pnl / pos.invested_brl) if pos.invested_brl > 0 else 0.0
        self.trade_returns.append(ret)

        if net_pnl > 0:
            self.trades_lucrativos += 1
        else:
            self.trades_prejuizo += 1

        self.trades.append(
            {
                "entry_time": pos.opened_at,
                "exit_time": when,
                "entry_price": pos.entry_price,
                "exit_price": exit_exec,
                "qty_btc": pos.qty_btc,
                "invested_brl": pos.invested_brl,
                "entry_fee": pos.entry_fee_brl,
                "exit_fee": exit_fee,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "reason": reason,
            }
        )

        self._log_trade(
            when=when,
            tipo="SELL",
            preco=exit_exec,
            quantidade=pos.qty_btc,
            fee=exit_fee,
            pnl_liquido=net_pnl,
            motivo=reason,
            saldo_apos=self.capital,
        )

        self.position = None
        self._update_drawdown(self.capital)

    def _build_stats(self) -> dict[str, Any]:
        gains = [float(t["net_pnl"]) for t in self.trades if float(t["net_pnl"]) > 0]
        losses = [float(t["net_pnl"]) for t in self.trades if float(t["net_pnl"]) <= 0]
        total_trades = len(self.trades)

        win_rate = (self.trades_lucrativos / total_trades) * 100.0 if total_trades > 0 else 0.0
        avg_gain = float(np.mean(gains)) if gains else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        payoff_medio = (avg_gain / abs(avg_loss)) if avg_loss < 0 else 0.0

        gross_profit = float(sum(gains)) if gains else 0.0
        gross_loss = float(abs(sum(losses))) if losses else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)

        ret_arr = np.array(self.trade_returns, dtype=float)
        if ret_arr.size > 1 and float(ret_arr.std(ddof=0)) > 0:
            sharpe = float(ret_arr.mean() / ret_arr.std(ddof=0) * np.sqrt(ret_arr.size))
        else:
            sharpe = 0.0

        retorno_total_pct = ((self.capital - self.initial_capital) / self.initial_capital) * 100.0 if self.initial_capital > 0 else 0.0

        return {
            "capital_inicial": self.initial_capital,
            "capital_final": self.capital,
            "total_cross": self.total_cross,
            "cross_filtrados": self.cross_filtrados,
            "cross_executados": self.cross_executados,
            "trades_lucrativos": self.trades_lucrativos,
            "trades_prejuizo": self.trades_prejuizo,
            "win_rate_pct": win_rate,
            "payoff_medio": payoff_medio,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "retorno_total_pct": retorno_total_pct,
            "drawdown_maximo_pct": self.max_drawdown_pct,
            "total_trades": total_trades,
            "equity_history": self.equity_history,
            "benchmark_history": self.benchmark_history,
            "trades": self.trades,
        }

    def _print_report(self, stats: dict[str, Any]) -> None:
        print("===== RELATÓRIO FINAL EMA7/SMA40 =====")
        print(f"Capital inicial: {float(stats['capital_inicial']):.2f}")
        print(f"Capital final: {float(stats['capital_final']):.2f}")
        print(f"Total cross: {int(stats['total_cross'])}")
        print(f"Cross filtrados: {int(stats['cross_filtrados'])}")
        print(f"Cross executados: {int(stats['cross_executados'])}")
        print(f"Trades lucrativos: {int(stats['trades_lucrativos'])}")
        print(f"Trades prejuízo: {int(stats['trades_prejuizo'])}")
        print(f"Win rate: {float(stats['win_rate_pct']):.2f}%")
        print(f"Payoff médio: {float(stats['payoff_medio']):.4f}")
        print(f"Profit factor: {float(stats['profit_factor']):.4f}")
        print(f"Sharpe ratio: {float(stats['sharpe_ratio']):.4f}")
        print(f"Retorno total: {float(stats['retorno_total_pct']):.2f}%")
        print(f"Máximo drawdown: {float(stats['drawdown_maximo_pct']):.2f}%")
        print("[SIMULATION END]")

    def _baixar_dados_binance(self) -> pd.DataFrame:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": self.cfg.symbol, "interval": self.cfg.interval, "limit": self.cfg.limit}
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Falha na API Binance: {exc}") from exc

        if not isinstance(data, list) or not data:
            raise RuntimeError("Resposta inválida da Binance.")

        cols = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        df = pd.DataFrame(data, columns=cols)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        return df.dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)

    def _preparar_indicadores(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema7"] = out["close"].ewm(span=7, adjust=False).mean()
        out["sma40"] = out["close"].rolling(window=40).mean()
        return out.dropna(subset=["ema7", "sma40"]).reset_index(drop=True)

    def _simulate_latency(self) -> int:
        ms = random.randint(self.cfg.latencia_min_ms, self.cfg.latencia_max_ms)
        if self.cfg.aplicar_sleep_latencia:
            time.sleep(ms / 1000.0)
        return ms

    def _apply_slippage(self, price: float, side: str) -> float:
        if side.lower() == "buy":
            return price * (1.0 + self.cfg.slippage_pct)
        return price * (1.0 - self.cfg.slippage_pct)

    def _equity_mark_to_market(self, mark_price: float) -> float:
        if self.position is None:
            return self.capital
        gross = self.position.qty_btc * mark_price
        exit_fee_est = gross * self.cfg.taxa_taker_pct
        return self.capital + max(0.0, gross - exit_fee_est)

    def _update_drawdown(self, equity: float) -> None:
        if equity > self.equity_peak:
            self.equity_peak = equity
        dd = ((self.equity_peak - equity) / self.equity_peak) * 100.0 if self.equity_peak > 0 else 0.0
        self.max_drawdown_pct = max(self.max_drawdown_pct, dd)

    def _ensure_log_header(self) -> None:
        if self.log_file.exists() and self.log_file.stat().st_size > 0:
            return
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write("data_hora | tipo | preco | quantidade | fee | pnl_liquido | motivo | saldo_apos\n")

    def _log_trade(
        self,
        when: datetime,
        tipo: str,
        preco: float,
        quantidade: float,
        fee: float,
        pnl_liquido: float,
        motivo: str,
        saldo_apos: float,
    ) -> None:
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write(
                f"{when.isoformat()} | {tipo} | {preco:.2f} | {quantidade:.8f} | "
                f"{fee:.2f} | {pnl_liquido:+.2f} | {motivo} | {saldo_apos:.2f}\n"
            )

    def _log_info(self, now: datetime, msg: str) -> None:
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write(f"{now.isoformat()} | INFO | {msg}\n")
