from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Fonte única de verdade — NUNCA leia de outro config.json
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "capital_total": 300,
    "risk_per_trade": 0.05,        # era 0.02
    "breakout_risk": 0.30,
    "binance_fee": 0.001,
    "symbol": "BTCUSDT",
    "modo": "simulacao",
    "trading_mode": "auto",
    "drawdown": 12.0,
    "position_scaling": [0.05, 0.05, 0.10],  # era [0.02, 0.02, 0.03]
    "max_position_size": 0.65,     # era 0.30
    "perfil": "Agressivo",
    "acumular_saldo": False,
    # Stop e take explícitos aqui — NÃO calculados via setdefault
    "stop": 1.5,                   # era 0.4 via setdefault
    "take": 4.0,                   # era 0.8 via setdefault
}


def _with_derived_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    capital = float(out.get("capital_total", 300))
    out["saldo_inicial"] = capital
    # REMOVIDO: valor_trade calculado aqui (era bug — gerava valores inconsistentes)
    # REMOVIDO: setdefault de stop/take (agora estão no DEFAULT_CONFIG)
    return out


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        cfg = _with_derived_fields(DEFAULT_CONFIG)
        print(f"[CONFIG] Criado novo: {CONFIG_PATH} | stop={cfg.get('stop')} take={cfg.get('take')}")
        return cfg

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
        print(
            f"[CONFIG] Carregado: {CONFIG_PATH.name} | "
            f"stop={loaded.get('stop')} take={loaded.get('take')} "
            f"max_pos={loaded.get('max_position_size')} perfil={loaded.get('perfil')}"
        )
    except Exception as e:
        print(f"[CONFIG] Erro ao carregar ({e}), usando DEFAULT")
        save_config(DEFAULT_CONFIG)
        return _with_derived_fields(DEFAULT_CONFIG)

    # DEFAULT primeiro, loaded sobrescreve — nunca o contrário
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