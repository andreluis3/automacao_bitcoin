"""
Sistema de logs profissional com pastas separadas por categoria.

Estrutura gerada:
logs/
  decisions/    → Por que o bot comprou/vendeu ou não
  market/       → Dados de mercado recebidos
  orders/       → Execução de ordens
  results/      → Resultado de cada trade
  errors/       → Erros do sistema
  state/        → Estado do bot
  strategy/     → Validação de confluências
  daily/        → Resumo diário consolidado
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ─── Cores ANSI para terminal ────────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"
    BOLD   = "\033[1m"


def _fmt(color: str, tag: str, msg: str) -> str:
    return f"{color}{C.BOLD}[{tag}]{C.RESET} {msg}"


# ─── Logger de arquivo por categoria ─────────────────────────────────────────
def _make_logger(name: str, log_dir: Path, filename: str) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"bot.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(log_dir / filename, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)

    return logger


# ─── BotLogger principal ──────────────────────────────────────────────────────
class BotLogger:
    """
    Sistema centralizado de logs com 8 categorias em pastas separadas.
    Uso:
        log = BotLogger(base_dir="logs")
        log.decision(price=63250, ema9=63200, ema21=63180, ...)
        log.order(side="BUY", price=63300, qty=0.002, ...)
        log.result(entry=63300, exit=63900, pnl_pct=0.95, ...)
        log.error("Binance API", "Timeout", "Reconnecting...")
    """

    def __init__(self, base_dir: str | Path = "logs"):
        self.base = Path(base_dir)
        today = datetime.utcnow().strftime("%Y-%m-%d")

        self._dec  = _make_logger("decisions", self.base / "decisions",  f"decisions_{today}.log")
        self._mkt  = _make_logger("market",    self.base / "market",     f"market_{today}.log")
        self._ord  = _make_logger("orders",    self.base / "orders",     f"orders_{today}.log")
        self._res  = _make_logger("results",   self.base / "results",    f"results_{today}.log")
        self._err  = _make_logger("errors",    self.base / "errors",     f"errors_{today}.log")
        self._sta  = _make_logger("state",     self.base / "state",      f"state_{today}.log")
        self._strat= _make_logger("strategy",  self.base / "strategy",   f"strategy_{today}.log")
        self._day  = _make_logger("daily",     self.base / "daily",      f"daily_{today}.log")

        # Também imprime no terminal com cores
        self._print_market_every = 30   # imprime mercado a cada N ticks
        self._market_tick_count  = 0

    # ─── 1. DECISION log ─────────────────────────────────────────────────────
    def decision(
        self,
        price: float,
        ema9: float,
        ema21: float,
        slope: float,
        dist_pct: float,
        atr: Optional[float],
        atr_gate: Optional[float],
        volume: float,
        avg_volume: float,
        regime: str,
        signal: str,
        reason: str,
        confluences: Optional[dict] = None,
    ) -> None:
        ok  = f"{C.GREEN}✔{C.RESET}"
        nok = f"{C.RED}✖{C.RESET}"

        ema_ok    = ema9 > ema21
        slope_ok  = slope > 0
        dist_ok   = dist_pct >= 0.0003
        atr_ok    = (atr is None) or (atr_gate is None) or (abs(ema9 - ema21) >= atr_gate)
        vol_ok    = avg_volume <= 0 or volume >= avg_volume * 0.8

        action_color = C.GREEN if signal == "buy" else (C.RED if signal == "sell" else C.YELLOW)
        action_label = "COMPROU" if signal == "buy" else ("VENDEU" if signal == "sell" else "NÃO OPEROU")

        lines = [
            f"\n{'─'*55}",
            f"  [DECISION] BTC/BRL",
            f"  Preço   : R$ {price:,.2f}",
            f"  EMA9    : {ema9:,.2f}   EMA21: {ema21:,.2f}",
            f"  Slope   : {slope:+.4f}   Dist: {dist_pct*100:.5f}%",
            f"  ATR     : {atr:.2f if atr else 'N/A'}   Gate: {atr_gate:.2f if atr_gate else 'N/A'}",
            f"  Regime  : {regime.upper()}",
            f"",
            f"  Confluências:",
            f"  {'✔' if ema_ok else '✖'} EMA9 > EMA21         ({ema9:.2f} vs {ema21:.2f})",
            f"  {'✔' if slope_ok else '✖'} Slope positivo       ({slope:+.4f})",
            f"  {'✔' if dist_ok else '✖'} Distância suficiente ({dist_pct*100:.5f}% >= 0.030%)",
            f"  {'✔' if atr_ok else '✖'} ATR gate ok",
            f"  {'✔' if vol_ok else '✖'} Volume ok            ({volume:.4f} vs avg {avg_volume:.4f})",
            f"",
            f"  Resultado: {action_color}{action_label}{C.RESET}",
            f"  Motivo  : {reason}",
            f"{'─'*55}",
        ]

        # terminal
        print("\n".join(lines))

        # arquivo (sem cores ANSI)
        clean_lines = [
            "─"*55,
            f"[DECISION] BTC/BRL",
            f"Preço   : R$ {price:,.2f}",
            f"EMA9    : {ema9:,.2f}   EMA21: {ema21:,.2f}",
            f"Slope   : {slope:+.4f}   Dist: {dist_pct*100:.5f}%",
            f"ATR     : {atr:.2f if atr else 'N/A'}   Gate: {atr_gate:.2f if atr_gate else 'N/A'}",
            f"Regime  : {regime.upper()}",
            f"EMA9>EMA21: {'SIM' if ema_ok else 'NAO'} | Slope+: {'SIM' if slope_ok else 'NAO'} | Dist: {'SIM' if dist_ok else 'NAO'} | ATR: {'SIM' if atr_ok else 'NAO'} | Vol: {'SIM' if vol_ok else 'NAO'}",
            f"Resultado: {action_label} | Motivo: {reason}",
            "─"*55,
        ]
        self._dec.info("\n".join(clean_lines))

    # ─── 2. MARKET log ───────────────────────────────────────────────────────
    def market(
        self,
        price: float,
        volume: float,
        ema9: float,
        ema21: float,
        atr: Optional[float],
        regime: str,
        timestamp: Optional[datetime] = None,
        force_print: bool = False,
    ) -> None:
        ts = (timestamp or datetime.utcnow()).strftime("%H:%M:%S")
        self._market_tick_count += 1
        msg = (
            f"[MARKET] {ts} | BTC R${price:,.2f} | "
            f"EMA9={ema9:.2f} EMA21={ema21:.2f} | "
            f"ATR={atr:.2f if atr else 'N/A'} | "
            f"Vol={volume:.4f} | Regime={regime.upper()}"
        )
        self._mkt.debug(msg)

        # Terminal: só a cada N ticks para não poluir
        if force_print or self._market_tick_count % self._print_market_every == 0:
            print(f"{C.GRAY}{msg}{C.RESET}")

    # ─── 3. ORDER log ────────────────────────────────────────────────────────
    def order(
        self,
        side: str,
        price: float,
        qty_btc: float,
        value_brl: float,
        fee_brl: float,
        reason: str,
        status: str = "EXECUTADA",
        error: str = "",
    ) -> None:
        color = C.GREEN if side == "BUY" else C.RED
        status_color = C.GREEN if status == "EXECUTADA" else C.RED

        terminal = (
            f"\n{color}{C.BOLD}{'─'*50}{C.RESET}\n"
            f"{color}  [ORDER] {side}{C.RESET}\n"
            f"  Par    : BTC/BRL\n"
            f"  Preço  : R$ {price:,.2f}\n"
            f"  Qtd    : {qty_btc:.8f} BTC\n"
            f"  Valor  : R$ {value_brl:.2f}\n"
            f"  Taxa   : R$ {fee_brl:.4f}\n"
            f"  Motivo : {reason}\n"
            f"  Status : {status_color}{status}{C.RESET}\n"
            f"  {f'Erro: {error}' if error else ''}\n"
            f"{color}{'─'*50}{C.RESET}"
        )
        print(terminal)

        file_msg = (
            f"[ORDER] {side} | BTC/BRL | "
            f"Preço=R${price:,.2f} | Qtd={qty_btc:.8f} BTC | "
            f"Valor=R${value_brl:.2f} | Taxa=R${fee_brl:.4f} | "
            f"Motivo={reason} | Status={status}"
            + (f" | ERRO={error}" if error else "")
        )
        self._ord.info(file_msg)

    # ─── 4. RESULT log ───────────────────────────────────────────────────────
    def result(
        self,
        entry_price: float,
        exit_price: float,
        qty_btc: float,
        pnl_brl: float,
        pnl_pct: float,
        duration_min: float,
        exit_reason: str,
        total_equity: float,
    ) -> None:
        color = C.GREEN if pnl_brl >= 0 else C.RED
        sign  = "+" if pnl_brl >= 0 else ""
        label = "LUCRO" if pnl_brl >= 0 else "PREJUÍZO"

        terminal = (
            f"\n{color}{C.BOLD}{'═'*50}{C.RESET}\n"
            f"{color}  [TRADE RESULT] {label}{C.RESET}\n"
            f"  Entrada : R$ {entry_price:,.2f}\n"
            f"  Saída   : R$ {exit_price:,.2f}\n"
            f"  Qtd     : {qty_btc:.8f} BTC\n"
            f"  PnL     : {color}{sign}R$ {pnl_brl:.4f} ({sign}{pnl_pct:.3f}%){C.RESET}\n"
            f"  Duração : {duration_min:.1f} min\n"
            f"  Motivo  : {exit_reason}\n"
            f"  Equity  : R$ {total_equity:.2f}\n"
            f"{color}{'═'*50}{C.RESET}"
        )
        print(terminal)

        file_msg = (
            f"[RESULT] {label} | "
            f"Entrada=R${entry_price:,.2f} | Saída=R${exit_price:,.2f} | "
            f"PnL={sign}R${pnl_brl:.4f} ({sign}{pnl_pct:.3f}%) | "
            f"Duração={duration_min:.1f}min | Motivo={exit_reason} | "
            f"Equity=R${total_equity:.2f}"
        )
        self._res.info(file_msg)

    # ─── 5. ERROR log ────────────────────────────────────────────────────────
    def error(self, module: str, error: str, action: str = "") -> None:
        terminal = (
            f"\n{C.RED}{C.BOLD}[ERROR]{C.RESET} "
            f"Módulo: {module} | Erro: {error}"
            + (f" | Ação: {action}" if action else "")
        )
        print(terminal)
        self._err.error(f"[ERROR] Módulo={module} | Erro={error}" + (f" | Ação={action}" if action else ""))

    # ─── 6. STATE log ────────────────────────────────────────────────────────
    def state(
        self,
        bot_state: str,
        mode: str,
        position_open: bool,
        drawdown_pct: float,
        equity: float,
        lucro_hoje: float,
        regime: str,
    ) -> None:
        pos_label = f"{C.GREEN}EM POSIÇÃO (comprado){C.RESET}" if position_open else "Sem posição"
        msg = (
            f"[STATE] {bot_state.upper()} | Modo={mode.upper()} | "
            f"Pos={'ABERTA' if position_open else 'NONE'} | "
            f"Equity=R${equity:.2f} | Drawdown={drawdown_pct:.2f}% | "
            f"LucroHoje=R${lucro_hoje:.4f} | Regime={regime.upper()}"
        )
        self._sta.debug(msg)

    # ─── 7. STRATEGY validation log ──────────────────────────────────────────
    def strategy_check(
        self,
        price: float,
        ema9: float,
        ema21: float,
        dist_pct: float,
        min_dist_pct: float,
        slope: float,
        atr: Optional[float],
        atr_gate: Optional[float],
        regime: str,
        passed: bool,
        reason: str,
    ) -> None:
        status = "✔ VÁLIDO" if passed else "✖ INVÁLIDO"
        msg = (
            f"[STRATEGY] {status} | "
            f"Dist={dist_pct*100:.5f}% (min={min_dist_pct*100:.3f}%) | "
            f"Slope={slope:+.4f} | "
            f"ATR={atr:.2f if atr else 'N/A'} Gate={atr_gate:.2f if atr_gate else 'N/A'} | "
            f"Regime={regime.upper()} | "
            f"Motivo={reason}"
        )
        self._strat.info(msg)
        # só imprime no terminal se inválido (para reduzir ruído)
        if not passed:
            print(f"{C.YELLOW}  [STRATEGY CHECK] {status} — {reason}{C.RESET}")

    # ─── 8. DAILY summary ────────────────────────────────────────────────────
    def daily_summary(
        self,
        date: str,
        trades: int,
        wins: int,
        losses: int,
        pnl_total: float,
        win_rate: float,
        drawdown_max: float,
        equity_inicial: float,
        equity_final: float,
    ) -> None:
        color = C.GREEN if pnl_total >= 0 else C.RED
        sign  = "+" if pnl_total >= 0 else ""
        terminal = (
            f"\n{C.BOLD}{'═'*55}{C.RESET}\n"
            f"{C.CYAN}  [RESUMO DIÁRIO] {date}{C.RESET}\n"
            f"  Trades  : {trades} ({wins} ganhos / {losses} perdas)\n"
            f"  Win rate: {win_rate*100:.1f}%\n"
            f"  PnL     : {color}{sign}R$ {pnl_total:.4f}{C.RESET}\n"
            f"  Equity  : R$ {equity_inicial:.2f} → R$ {equity_final:.2f}\n"
            f"  Drawdown: {drawdown_max:.2f}%\n"
            f"{'═'*55}"
        )
        print(terminal)

        msg = (
            f"[DAILY] {date} | Trades={trades} W={wins} L={losses} | "
            f"WinRate={win_rate*100:.1f}% | PnL={sign}R${pnl_total:.4f} | "
            f"Equity={equity_inicial:.2f}->{equity_final:.2f} | MaxDD={drawdown_max:.2f}%"
        )
        self._day.info(msg)

    # ─── helper: log de confluência rápida ───────────────────────────────────
    def confluence_quick(self, price: float, checks: dict[str, bool], final: str) -> None:
        """Log rápido de confluência para o terminal durante operação normal."""
        ok  = "✔"
        nok = "✖"
        parts = [f"  [{ok if v else nok}] {k}" for k, v in checks.items()]
        passed = sum(checks.values())
        total  = len(checks)
        color  = C.GREEN if passed == total else (C.YELLOW if passed >= total // 2 else C.RED)
        lines  = [
            f"{color}  [CONFLUENCE] R${price:,.2f} — {passed}/{total} ok{C.RESET}",
            *parts,
            f"  → {final}",
        ]
        print("\n".join(lines))