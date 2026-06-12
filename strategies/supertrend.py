"""
Supertrend strategy.

The Supertrend indicator places a dynamic ATR-based band above/below price.
When price is above the lower band → uptrend. Below the upper band → downtrend.
The band itself acts as a trailing stop-loss level.

Logic:
  - Enter LONG  when Supertrend flips from downtrend to uptrend.
  - Enter SHORT when Supertrend flips from uptrend to downtrend.
  - SL: the active Supertrend band (lower band for longs, upper for shorts).
    This is a trailing stop; as price moves in our favour, the band tightens.
  - TP: risk:reward multiple of the initial SL distance.
  - Exit: Supertrend flips against position.

This strategy is pure trend-following. It has many false signals in sideways
markets but captures large trends well. Use on 1h+ timeframes.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import supertrend, atr


class Supertrend(Strategy):
    name = "supertrend"
    warmup = 30

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        period     = p.get("st_period", 10)
        multiplier = p.get("st_multiplier", 3.0)
        rr         = p.get("risk_reward", 2.0)
        atr_period = p.get("atr_period", 14)
        atr_mult   = p.get("atr_mult", 1.0)  # extra buffer added to ST band for SL

        df = candles.copy()
        trend = supertrend(df, period, multiplier)
        df["trend"]  = trend
        df["st_upper"] = trend.attrs["upper"]
        df["st_lower"] = trend.attrs["lower"]
        df["atr"] = atr(df, atr_period)

        if df["trend"].iloc[-1] != df["trend"].iloc[-1]:
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        price = last["close"]
        a     = last["atr"]

        flipped_up   = prev["trend"] == -1 and last["trend"] == 1
        flipped_down = prev["trend"] == 1  and last["trend"] == -1

        # Exit: ST flips against position
        if position and position.is_open():
            if position.side == Side.LONG and flipped_down:
                return Signal(SignalType.CLOSE, price, reason="supertrend flip down")
            if position.side == Side.SHORT and flipped_up:
                return Signal(SignalType.CLOSE, price, reason="supertrend flip up")
            return Signal(SignalType.HOLD, price, reason="holding")

        if flipped_up:
            # SL = ST lower band minus a small ATR buffer
            sl = last["st_lower"] - atr_mult * a
            risk = price - sl
            tp = price + rr * risk if risk > 0 else price + 2 * a
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason="supertrend flip up")

        if flipped_down:
            sl = last["st_upper"] + atr_mult * a
            risk = sl - price
            tp = price - rr * risk if risk > 0 else price - 2 * a
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason="supertrend flip down")

        return Signal(SignalType.HOLD, price, reason="no signal")
