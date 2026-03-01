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
    limit: int = 200

    capital_inicial: float = 10000.0
    valor_trade_pct: float = 0.05

    take_profit_pct: float = 0.012
    stop_loss_pct: float = 0.006
    breakeven_trigger_pct: float = 0.005

    slippage_pct: float = 0.0002
    taxa_maker_pct: float = 0.0002
    taxa_taker_pct: float = 0.0004

    max_drawdown_pct: float = 8.0
    limite_perda_diaria_pct: float = 2.0

    latencia_min_ms: int = 100
    latencia_max_ms: int = 300
    aplicar_sleep_latencia: bool = True

    modo: str = "conservador"
    log_path: str = "simulation_log.txt"


@dataclass
class Position:
    entry_time: datetime
    entry_price: float
    qty_btc: float
    invested_brl: float
    stop_price: float
    take_price: float
    fees_entry_brl: float
    breakeven_ativado: bool = False


class RiskController:
    def __init__(self, cfg: SimulationConfig):
        self.cfg = cfg
        self.equity_peak = cfg.capital_inicial
        self.max_drawdown = 0.0
        self.pause_by_drawdown = False
        self.current_day: str | None = None
        self.equity_day_start: float = cfg.capital_inicial
        self.day_locked = False

    def reset_day_if_needed(self, now: datetime, equity: float) -> None:
        day_key = now.date().isoformat()
        if self.current_day != day_key:
            self.current_day = day_key
            self.equity_day_start = equity
            self.day_locked = False

    def update_drawdown(self, equity: float) -> float:
        if equity > self.equity_peak:
            self.equity_peak = equity
        drawdown = ((self.equity_peak - equity) / self.equity_peak) * 100.0 if self.equity_peak > 0 else 0.0
        self.max_drawdown = max(self.max_drawdown, drawdown)
        if drawdown >= self.cfg.max_drawdown_pct:
            self.pause_by_drawdown = True
        return drawdown

    def daily_loss_pct(self, equity: float) -> float:
        if self.equity_day_start <= 0:
            return 0.0
        return max(0.0, ((self.equity_day_start - equity) / self.equity_day_start) * 100.0)

    def can_open_trade(self, now: datetime, equity: float) -> tuple[bool, str]:
        self.reset_day_if_needed(now, equity)
        if self.pause_by_drawdown:
            return False, "pausado_drawdown"

        perda_dia = self.daily_loss_pct(equity)
        if perda_dia >= self.cfg.limite_perda_diaria_pct:
            self.day_locked = True
        if self.day_locked:
            return False, "limite_perda_diaria"

        return True, "ok"


class SimulationEngine:
    """
    Motor de simulacao isolado, sem ordens reais.
    """

    def __init__(self, config: SimulationConfig | None = None):
        self.cfg = config or SimulationConfig()
        self.position: Position | None = None
        self.risk = RiskController(self.cfg)

        self.capital = float(self.cfg.capital_inicial)
        self.initial_capital = float(self.cfg.capital_inicial)
        self.equity_curve: list[float] = [self.capital]
        self.trade_returns: list[float] = []
        self.trades: list[dict[str, Any]] = []

        self.log_file = Path(self.cfg.log_path)
        self._ensure_log_header()

    def rodar(self) -> dict[str, Any]:
        try:
            df = self._baixar_dados_binance()
            if df.empty:
                raise RuntimeError("Sem dados para simular.")
            df = self._preparar_indicadores(df)
        except Exception as exc:
            print(f"[ERROR] {exc}")
            return {"ok": False, "error": str(exc)}

        print("[SIMULATION START]")

        for _, row in df.iterrows():
            now = row["open_time"]
            open_p = float(row["open"])
            high_p = float(row["high"])
            low_p = float(row["low"])
            close_p = float(row["close"])

            equity_mark = self._equity_mark_to_market(close_p)
            dd = self.atualizar_drawdown(equity_mark)
            can_trade, reason_lock = self.risk.can_open_trade(now, equity_mark)

            print(
                f"[CANDLE] Data={now} | Preco={close_p:.2f} | EMA={float(row['ema9']):.2f} | "
                f"SMA={float(row['sma21']):.2f} | RSI={float(row['rsi']):.2f} | Vol={float(row['volume']):.2f} | "
                f"Equity={equity_mark:.2f} | Drawdown={dd:.2f}% | EmPosicao={'SIM' if self.position else 'NAO'}"
            )

            if self.position is not None:
                self.aplicar_breakeven(high_p)
                closed = self.verificar_stop_take(
                    when=now,
                    candle_open=open_p,
                    candle_high=high_p,
                    candle_low=low_p,
                    candle_close=close_p,
                    row=row,
                )
                if closed:
                    continue

            if self.position is None and can_trade:
                signal_ok, signal_reason = self.verificar_sinal(row)
                if signal_ok:
                    self.abrir_posicao(now=now, reference_price=close_p, motivo=signal_reason)
            elif self.position is None and not can_trade:
                print(f"[RISK BLOCK] {reason_lock}")

        if self.position is not None:
            last = df.iloc[-1]
            self._fechar_posicao(
                when=last["close_time"],
                exit_ref_price=float(last["close"]),
                motivo="encerramento_simulacao",
                fee_type="taker",
                is_aggressive=True,
            )

        stats = self.calcular_estatisticas()
        self.imprimir_relatorio(stats)
        return {"ok": True, **stats}

    def verificar_sinal(self, row: pd.Series) -> tuple[bool, str]:
        ema9 = float(row["ema9"])
        sma21 = float(row["sma21"])
        close_p = float(row["close"])
        rsi = float(row["rsi"])
        volume = float(row["volume"])
        vol_mean = float(row["vol_mean"])
        bb_width = float(row["bb_width"])
        bb_width_mean = float(row["bb_width_mean"])
        sma_slope = float(row["sma21_slope"])

        cond_histerese = ema9 > (sma21 * (1.0 + 0.005))
        cond_pullback = close_p < (sma21 * 0.98)
        cond_rsi = rsi < 30.0
        cond_vol = volume > (vol_mean * 1.2)
        cond_bb = bb_width > bb_width_mean

        # Filtro de tendencia obrigatorio
        cond_trend_slope = sma_slope > 0.0
        cond_price_above_sma = close_p > sma21

        ok = cond_histerese and cond_pullback and cond_rsi and cond_vol and cond_bb and cond_trend_slope and cond_price_above_sma
        reasons = []
        if cond_histerese:
            reasons.append("EMA9>SMA21+0.5%")
        if cond_pullback:
            reasons.append("preco<SMA21*0.98")
        if cond_rsi:
            reasons.append("RSI<30")
        if cond_vol:
            reasons.append("volume>1.2x")
        if cond_bb:
            reasons.append("bb_width_expandindo")
        if cond_trend_slope:
            reasons.append("sma_lenta_inclinacao_positiva")
        if cond_price_above_sma:
            reasons.append("preco_acima_sma_lenta")

        return ok, ", ".join(reasons) if reasons else "sem_condicoes"

    def abrir_posicao(self, now: datetime, reference_price: float, motivo: str) -> None:
        if self.position is not None:
            return
        if reference_price <= 0:
            return

        self._simular_latencia()
        equity_now = self._equity_mark_to_market(reference_price)
        quote_brl = min(self.capital, max(0.0, equity_now * self.cfg.valor_trade_pct))
        if quote_brl <= 0:
            return

        entry_exec = self._apply_slippage(reference_price, side="buy")
        fee_entry = quote_brl * self.cfg.taxa_taker_pct  # entrada agressiva
        btc_qty = max(0.0, (quote_brl - fee_entry) / entry_exec)
        if btc_qty <= 0:
            return

        self.capital = max(0.0, self.capital - quote_brl)
        stop = entry_exec * (1.0 - self.cfg.stop_loss_pct)
        take = entry_exec * (1.0 + self.cfg.take_profit_pct)

        self.position = Position(
            entry_time=now,
            entry_price=entry_exec,
            qty_btc=btc_qty,
            invested_brl=quote_brl,
            stop_price=stop,
            take_price=take,
            fees_entry_brl=fee_entry,
            breakeven_ativado=False,
        )

        print("[ABERTURA]")
        print(f"Data: {now}")
        print(f"Preco entrada: {entry_exec:.2f}")
        print(f"Quantidade: {btc_qty:.8f}")
        print(f"Stop: {stop:.2f}")
        print(f"Take: {take:.2f}")
        print(f"Motivo: {motivo}")

        self._log_operacao(
            when=now,
            tipo="ABERTURA",
            preco=entry_exec,
            quantidade=btc_qty,
            stop=stop,
            saldo_apos=self.capital,
        )

    def verificar_stop_take(
        self,
        when: datetime,
        candle_open: float,
        candle_high: float,
        candle_low: float,
        candle_close: float,
        row: pd.Series,
    ) -> bool:
        if self.position is None:
            return False

        pos = self.position
        stop_hit = candle_low <= pos.stop_price
        take_hit = candle_high >= pos.take_price

        # Se ambos tocam no mesmo candle, aplica prioridade conservadora: STOP primeiro.
        if stop_hit:
            self._fechar_posicao(
                when=when,
                exit_ref_price=pos.stop_price,
                motivo="stop",
                fee_type="taker",
                is_aggressive=True,
            )
            return True

        if take_hit:
            self._fechar_posicao(
                when=when,
                exit_ref_price=pos.take_price,
                motivo="take",
                fee_type="maker",
                is_aggressive=False,
            )
            return True

        # Saida por cruzamento contrario (agressiva no fechamento do candle)
        if float(row["ema9"]) < float(row["sma21"]):
            self._fechar_posicao(
                when=when,
                exit_ref_price=candle_close,
                motivo="sinal_contrario",
                fee_type="taker",
                is_aggressive=True,
            )
            return True

        return False

    def aplicar_breakeven(self, candle_high: float) -> None:
        if self.position is None:
            return

        pos = self.position
        if pos.breakeven_ativado:
            return

        trigger = pos.entry_price * (1.0 + self.cfg.breakeven_trigger_pct)
        if candle_high >= trigger:
            # Stop no breakeven considerando custo de entrada e custo estimado de saida.
            fee_entry_rate = self.cfg.taxa_taker_pct
            fee_exit_rate = self.cfg.taxa_taker_pct
            breakeven_price = pos.entry_price * (1.0 + fee_entry_rate + fee_exit_rate)
            if breakeven_price > pos.stop_price:
                pos.stop_price = breakeven_price
                pos.breakeven_ativado = True
                print("[BREAKEVEN ATIVADO]")
                print(f"Novo stop: {pos.stop_price:.2f}")

    def atualizar_drawdown(self, equity: float) -> float:
        return self.risk.update_drawdown(equity)

    def calcular_estatisticas(self) -> dict[str, float]:
        total_trades = len(self.trades)
        wins = [t["net_pnl"] for t in self.trades if t["net_pnl"] > 0]
        losses = [t["net_pnl"] for t in self.trades if t["net_pnl"] <= 0]

        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        payoff_medio = (avg_win / abs(avg_loss)) if avg_loss < 0 else 0.0
        expectativa = (win_rate / 100.0) * avg_win + (1.0 - win_rate / 100.0) * avg_loss

        gross_profit = float(sum(wins)) if wins else 0.0
        gross_loss = float(abs(sum(losses))) if losses else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else math.inf if gross_profit > 0 else 0.0

        ret_arr = np.array(self.trade_returns, dtype=float)
        if ret_arr.size > 1 and float(ret_arr.std(ddof=0)) > 0:
            sharpe = float(ret_arr.mean() / ret_arr.std(ddof=0) * np.sqrt(ret_arr.size))
        else:
            sharpe = 0.0

        retorno_total_pct = ((self.capital - self.initial_capital) / self.initial_capital * 100.0) if self.initial_capital > 0 else 0.0

        return {
            "capital_inicial": self.initial_capital,
            "capital_final": self.capital,
            "retorno_total_pct": retorno_total_pct,
            "drawdown_maximo_pct": self.risk.max_drawdown,
            "win_rate_pct": win_rate,
            "payoff_medio": payoff_medio,
            "expectativa": expectativa,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "total_trades": float(total_trades),
        }

    def imprimir_relatorio(self, stats: dict[str, float]) -> None:
        print("===== RELATÓRIO FINAL =====")
        print(f"Capital inicial: {stats['capital_inicial']:.2f}")
        print(f"Capital final: {stats['capital_final']:.2f}")
        print(f"Retorno %: {stats['retorno_total_pct']:.2f}%")
        print(f"Drawdown máximo: {stats['drawdown_maximo_pct']:.2f}%")
        print(f"Win rate: {stats['win_rate_pct']:.2f}%")
        print(f"Expectativa: {stats['expectativa']:.4f}")
        print(f"Profit factor: {stats['profit_factor']:.4f}")
        print(f"Sharpe ratio: {stats['sharpe_ratio']:.4f}")
        print(f"Total trades: {int(stats['total_trades'])}")
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

        if not isinstance(data, list) or len(data) == 0:
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
        out["ema9"] = out["close"].ewm(span=9, adjust=False).mean()
        out["sma21"] = out["close"].rolling(window=21).mean()
        out["sma21_prev"] = out["sma21"].shift(1)
        out["sma21_slope"] = out["sma21"] - out["sma21_prev"]

        delta = out["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        out["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        out["vol_mean"] = out["volume"].rolling(window=20).mean()
        bb_mid = out["close"].rolling(window=20).mean()
        bb_std = out["close"].rolling(window=20).std(ddof=0)
        bb_upper = bb_mid + 2.0 * bb_std
        bb_lower = bb_mid - 2.0 * bb_std
        out["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0.0, np.nan)
        out["bb_width_mean"] = out["bb_width"].rolling(window=20).mean()

        return out.dropna(
            subset=["ema9", "sma21", "sma21_slope", "rsi", "vol_mean", "bb_width", "bb_width_mean"]
        ).reset_index(drop=True)

    def _simular_latencia(self) -> int:
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

    def _fechar_posicao(
        self,
        when: datetime,
        exit_ref_price: float,
        motivo: str,
        fee_type: str,
        is_aggressive: bool,
    ) -> None:
        if self.position is None:
            return

        self._simular_latencia()
        pos = self.position
        exit_exec = self._apply_slippage(exit_ref_price, side="sell")
        fee_rate = self.cfg.taxa_taker_pct if fee_type == "taker" else self.cfg.taxa_maker_pct

        gross = pos.qty_btc * exit_exec
        fee_exit = gross * fee_rate
        net_exit = gross - fee_exit
        self.capital = max(0.0, self.capital + net_exit)

        gross_pnl = gross - pos.invested_brl
        total_fees = pos.fees_entry_brl + fee_exit
        net_pnl = gross_pnl - pos.fees_entry_brl - fee_exit
        ret = (net_pnl / pos.invested_brl) if pos.invested_brl > 0 else 0.0

        self.trade_returns.append(ret)
        self.trades.append(
            {
                "entry_time": pos.entry_time,
                "exit_time": when,
                "entry_price": pos.entry_price,
                "exit_price": exit_exec,
                "gross_pnl": gross_pnl,
                "fees": total_fees,
                "net_pnl": net_pnl,
                "reason": motivo,
                "aggressive": is_aggressive,
            }
        )

        print("[FECHAMENTO]")
        print(f"Tipo: {motivo}")
        print(f"Preço saída: {exit_exec:.2f}")
        print(f"Lucro bruto: {gross_pnl:+.2f}")
        print(f"Taxas: {total_fees:.2f}")
        print(f"Lucro líquido: {net_pnl:+.2f}")
        print(f"Equity atual: {self.capital:.2f}")

        self._log_operacao(
            when=when,
            tipo=f"FECHAMENTO_{motivo}",
            preco=exit_exec,
            quantidade=pos.qty_btc,
            stop=pos.stop_price,
            saldo_apos=self.capital,
        )

        self.position = None
        self.equity_curve.append(self.capital)
        self.atualizar_drawdown(self.capital)

    def _ensure_log_header(self) -> None:
        if self.log_file.exists() and self.log_file.stat().st_size > 0:
            return
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write("data_hora | tipo_operacao | preco | quantidade | stop_atual | saldo_apos_operacao\n")

    def _log_operacao(
        self,
        when: datetime,
        tipo: str,
        preco: float,
        quantidade: float,
        stop: float,
        saldo_apos: float,
    ) -> None:
        with self.log_file.open("a", encoding="utf-8") as fp:
            fp.write(
                f"{when.isoformat()} | {tipo} | {preco:.2f} | {quantidade:.8f} | {stop:.2f} | {saldo_apos:.2f}\n"
            )

