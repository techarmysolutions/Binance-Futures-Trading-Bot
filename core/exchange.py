"""
Binance USDⓈ-M Futures connector.

Wraps python-binance so the rest of the bot never touches the SDK directly.
Supports testnet (paper) and mainnet (live). All order placement goes through
`open_position` which ALSO places the protective stop-loss as a separate
reduce-only STOP_MARKET order — so a crashed bot still has downside protection
sitting on the exchange.
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

try:
    from binance.client import Client
    from binance.enums import (
        SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET,
        FUTURE_ORDER_TYPE_STOP_MARKET, FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
    )
except ImportError:  # allow import for backtest-only environments
    Client = None

from core.models import Candle, Position, Side


class BinanceFutures:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        if Client is None:
            raise RuntimeError("python-binance not installed. pip install python-binance")
        self.client = Client(api_key, api_secret, testnet=testnet)
        self.testnet = testnet

    # ---- market data ---------------------------------------------------
    def get_klines(self, pair: str, interval: str, limit: int = 200) -> pd.DataFrame:
        raw = self.client.futures_klines(symbol=pair, interval=interval, limit=limit)
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbav", "tqav", "ignore",
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

    # ---- account ------------------------------------------------------
    def get_balance(self) -> float:
        for asset in self.client.futures_account_balance():
            if asset["asset"] == "USDT":
                return float(asset["balance"])
        return 0.0

    def get_position(self, pair: str) -> Optional[Position]:
        for p in self.client.futures_position_information(symbol=pair):
            amt = float(p["positionAmt"])
            if amt == 0:
                continue
            return Position(
                pair=pair,
                side=Side.LONG if amt > 0 else Side.SHORT,
                entry_price=float(p["entryPrice"]),
                quantity=abs(amt),
                leverage=1,  # Binance doesn't return leverage per position; track separately if needed
                stop_loss=0.0,
                unrealized_pnl=float(p["unRealizedProfit"]),
            )
        return None

    # ---- trading ------------------------------------------------------
    def set_leverage(self, pair: str, leverage: int) -> None:
        self.client.futures_change_leverage(symbol=pair, leverage=leverage)

    def open_position(self, pair: str, side: Side, quantity: float,
                      stop_loss: float, take_profit: Optional[float] = None) -> dict:
        """Market entry + protective stop (and optional TP) as reduce-only orders.

        Caller must call set_leverage() BEFORE this method — it is NOT set here.
        """
        entry_side = SIDE_BUY if side == Side.LONG else SIDE_SELL
        exit_side = SIDE_SELL if side == Side.LONG else SIDE_BUY
        pos_side = "LONG" if side == Side.LONG else "SHORT"

        entry = self.client.futures_create_order(
            symbol=pair, side=entry_side, type=ORDER_TYPE_MARKET,
            quantity=quantity, positionSide=pos_side,
        )
        # Protective stop sits ON the exchange — survives bot crash.
        stop = self.client.futures_create_order(
            symbol=pair, side=exit_side, type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop_loss, 2), closePosition=True,
        )
        tp = None
        if take_profit:
            tp = self.client.futures_create_order(
                symbol=pair, side=exit_side, type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=round(take_profit, 2), closePosition=True,
            )
        return {"entry": entry, "stop": stop, "take_profit": tp}

    def close_position(self, pair: str, side: Side, quantity: float) -> dict:
        exit_side = SIDE_SELL if side == Side.LONG else SIDE_BUY
        self.client.futures_cancel_all_open_orders(symbol=pair)
        # In hedge mode: specify positionSide to target the correct direction
        return self.client.futures_create_order(
            symbol=pair, side=exit_side, type=ORDER_TYPE_MARKET,
            quantity=quantity,
            positionSide="LONG" if side == Side.LONG else "SHORT",
        )
