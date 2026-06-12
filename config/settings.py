"""Loads config from config.yaml + environment variables."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from risk.manager import RiskConfig


def load_config(path: str = "config.yaml") -> dict:
    cfg = {}
    p = Path(path)
    if p.exists():
        cfg = yaml.safe_load(p.read_text()) or {}

    # Secrets ALWAYS from env, never from the yaml file.
    cfg["api_key"] = os.getenv("BINANCE_API_KEY", "")
    cfg["api_secret"] = os.getenv("BINANCE_API_SECRET", "")
    return cfg


def risk_from_config(cfg: dict) -> RiskConfig:
    r = cfg.get("risk", {})
    return RiskConfig(
        risk_per_trade=r.get("risk_per_trade", 0.01),
        max_leverage=r.get("max_leverage", 5),
        max_positions=r.get("max_positions", 3),
        daily_loss_limit=r.get("daily_loss_limit", 0.05),
        max_drawdown=r.get("max_drawdown", 0.20),
        min_notional=r.get("min_notional", 5.0),
    )
