"""
CLI entrypoint.

  python main.py backtest --strategy ema_cross --pair BTCUSDT --interval 1h --days 90
  python main.py paper    --strategy ema_cross --pair BTCUSDT --interval 15m
  python main.py live     --strategy ema_cross --pair BTCUSDT --interval 15m
"""
from __future__ import annotations

import argparse
import importlib
import sys

from config.settings import load_config, risk_from_config
from risk.manager import RiskManager


STRATEGY_REGISTRY = {
    "ema_cross":          ("strategies.ema_cross",          "EmaCross"),
    "rsi_mean_reversion": ("strategies.rsi_mean_reversion", "RsiMeanReversion"),
    "bb_squeeze":         ("strategies.bb_squeeze",         "BbSqueeze"),
    "macd_signal":        ("strategies.macd_signal",        "MacdSignal"),
    "supertrend":         ("strategies.supertrend",         "Supertrend"),
    "donchian_breakout":  ("strategies.donchian_breakout",  "DonchianBreakout"),
    "vwap_reversion":     ("strategies.vwap_reversion",     "VwapReversion"),
    "vrvp_poc":           ("strategies.vrvp_poc",           "VrvpPoc"),
    "scalper":            ("strategies.scalper",            "Scalper"),
}


def load_strategy(name: str, params: dict):
    if name not in STRATEGY_REGISTRY:
        sys.exit(f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY)}")
    module_path, cls_name = STRATEGY_REGISTRY[name]
    cls = getattr(importlib.import_module(module_path), cls_name)
    return cls(params)


def cmd_backtest(args, cfg):
    import pandas as pd
    from core.exchange import BinanceFutures
    from backtest.engine import Backtester

    risk = RiskManager(risk_from_config(cfg))
    strat = load_strategy(args.strategy, cfg.get("strategy_params", {}))

    # Pull history from public endpoints (no keys needed for klines).
    ex = BinanceFutures(cfg["api_key"] or "x", cfg["api_secret"] or "x", testnet=False)
    bars_needed = min(args.days * (24 if "h" in args.interval else 1) * 60, 1500)
    df = ex.get_klines(args.pair, args.interval, limit=min(bars_needed, 1500))

    bt = Backtester(strat, risk, start_equity=cfg.get("start_equity", 1000),
                    leverage=args.leverage)
    result = bt.run(df, args.pair)
    print("\n=== Backtest summary ===")
    for k, v in result.summary().items():
        print(f"  {k:18} {v}")


def cmd_trade(args, cfg, testnet: bool):
    from core.exchange import BinanceFutures
    from core.engine import TradingEngine

    if not cfg["api_key"]:
        sys.exit("Set BINANCE_API_KEY / BINANCE_API_SECRET env vars first.")

    if not testnet:
        confirm = input("⚠  LIVE trading with REAL money. Type 'I ACCEPT THE RISK': ")
        if confirm.strip() != "I ACCEPT THE RISK":
            sys.exit("Aborted.")

    risk = RiskManager(risk_from_config(cfg))
    strat = load_strategy(args.strategy, cfg.get("strategy_params", {}))
    ex = BinanceFutures(cfg["api_key"], cfg["api_secret"], testnet=testnet)
    engine = TradingEngine(ex, strat, risk, args.pair, args.interval, args.leverage)
    engine.run_forever()


def main():
    p = argparse.ArgumentParser(description="Custom Binance Futures bot")
    sub = p.add_subparsers(dest="mode", required=True)
    for mode in ("backtest", "paper", "live"):
        sp = sub.add_parser(mode)
        sp.add_argument("--strategy", default="ema_cross")
        sp.add_argument("--pair", default="BTCUSDT")
        sp.add_argument("--interval", default="15m")
        sp.add_argument("--leverage", type=int, default=3)
        sp.add_argument("--days", type=int, default=30)  # backtest only

    args = p.parse_args()
    cfg = load_config()

    if args.mode == "backtest":
        cmd_backtest(args, cfg)
    elif args.mode == "paper":
        cmd_trade(args, cfg, testnet=True)
    elif args.mode == "live":
        cmd_trade(args, cfg, testnet=False)


if __name__ == "__main__":
    main()
