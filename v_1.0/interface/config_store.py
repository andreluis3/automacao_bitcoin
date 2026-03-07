from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "modo": "simulacao",
    "trading_mode": "auto",
    "perfil": "Conservador",
    "acumular_saldo": False,
    "saldo_inicial": 10000.0,
    "stop": 0.6,
    "take": 1.2,
    "valor_trade": 5.0,
    "drawdown": 12.0,
}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
    except Exception:
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    if isinstance(loaded, dict):
        merged.update(loaded)

    save_config(merged)
    return merged


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)
