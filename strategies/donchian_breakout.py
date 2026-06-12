"""
Donchian Channel Breakout strategy.

Classic trend-following breakout system (popularized by the Turtle Traders).

Logic:
  - Enter LONG  when close breaks above the N-bar highest high (excluding current bar).
  - Enter SHORT when close breaks below the N-bar lowest low.
  - Exit with a shorter M-bar channel (exit_period < entry_period) — prices
    breaking back into the channel signal trend exhaustion.
  - SL: ATR-based from entry. The Donchian channel is wide; ATR stop keeps
    risk controlled on shorter timeframes.
  - TP: risk:reward ratio.

Classic params: entry_period=20, exit_period=10 (Turtle system).
Works best on trending assets on 1h+ timeframes. Generates fewer but
higher-conviction signals.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import atr


class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    warmup = 55

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        entry_period = p.get("entry_period", 20)
        exit_period  = p.get("exit_period", 10)
        atr_period   = p.get("atr_period", 14)
        atr_mult     = p.get("atr_mult", 2.0)
        rr           = p.get("risk_reward", 2.0)

        df = candles.copy()
        df["atr"] = atr(df, atr_period)

        # Channels: use all bars BEFORE the current bar (no look-ahead)
        df["entry_high"] = df["high"].shift(1).rolling(entry_period).max()
        df["entry_low"]  = df["low"].shift(1).rolling(entry_period).min()
        df["exit_high"]  = df["high"].shift(1).rolling(exit_period).max()
        df["exit_low"]   = df["low"].shift(1).rolling(exit_period).min()

        if df["entry_high"].iloc[-1] != df["entry_high"].iloc[-1]:
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        price = last["close"]
        a     = last["atr"]

        broke_high = price > last["entry_high"]
        broke_low  = price < last["entry_low"]
        exit_short = price > last["exit_high"]  # short exit: price recovers above exit channel
        exit_long  = price < last["exit_low"]   # long exit: price falls below exit channel

        # Exit via shorter channel
        if position and position.is_open():
            if position.side == Side.LONG and exit_long:
                return Signal(SignalType.CLOSE, price,
                              reason=f"exit channel low ({last['exit_low']:.2f})")
            if position.side == Side.SHORT and exit_short:
                return Signal(SignalType.CLOSE, price,
                              reason=f"exit channel high ({last['exit_high']:.2f})")
            return Signal(SignalType.HOLD, price, reason="holding")

        if broke_high:
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"breakout above {last['entry_high']:.2f}")

        if broke_low:
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"breakout below {last['entry_low']:.2f}")

        return Signal(SignalType.HOLD, price, reason="inside channel")
