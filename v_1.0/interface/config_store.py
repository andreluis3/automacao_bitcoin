from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "capital_total": 300,
    "risk_per_trade": 0.05,
    "breakout_risk": 0.30,
    "binance_fee": 0.001,
    "symbol": "BTCUSDT",
    "modo": "simulacao",
    "trading_mode": "auto",
    "drawdown": 12.0,
    "position_scaling": [0.05, 0.05, 0.10],
    "max_position_size": 0.65,
    "perfil": "Agressivo",
    "acumular_saldo": False,
    "stop": 1.5,
    "take": 4.0,
}


def _with_derived_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    capital = float(out.get("capital_total", 300))
    out["saldo_inicial"] = capital
    # REMOVIDO: valor_trade calculado aqui — vem só do JSON
    # REMOVIDO: setdefault de stop/take — estão no DEFAULT_CONFIG
    return out


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return _with_derived_fields(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
        print(
            f"[CONFIG] {CONFIG_PATH.name} | "
            f"stop={loaded.get('stop')} take={loaded.get('take')} "
            f"max_pos={loaded.get('max_position_size')}"
        )
    except Exception as e:
        print(f"[CONFIG] Erro, usando DEFAULT: {e}")
        save_config(DEFAULT_CONFIG)
        return _with_derived_fields(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(loaded)
    merged = _with_derived_fields(merged)
    save_config(merged)
    return merged


def _with_derived_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    capital = float(out.get("capital_total", 300))
    risk_pct = float(out.get("risk_per_trade", 0.02))
    out["saldo_inicial"] = capital
    out["valor_trade"] = max(0.1, risk_pct * 100.0)
    out.setdefault("stop", 0.4)
    out.setdefault("take", 0.8)
    return out


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return _with_derived_fields(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
    except Exception:
        save_config(DEFAULT_CONFIG)
        return _with_derived_fields(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    if isinstance(loaded, dict):
        merged.update(loaded)
    merged = _with_derived_fields(merged)
    save_config(merged)
    return merged


def save_config(config: dict[str, Any]) -> None:
    payload = _with_derived_fields(config)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
