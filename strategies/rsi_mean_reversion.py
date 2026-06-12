"""
RSI Mean Reversion strategy.

Logic:
  - Long  when RSI crosses back ABOVE oversold level (was below, now above).
  - Short when RSI crosses back BELOW overbought level (was above, now below).
  - SL: entry +/- (atr_mult * ATR).
  - TP: risk:reward ratio from params.
  - Exit: RSI reaches mid-zone (default 50) or opposite extreme.

This strategy works best on ranging/oscillating markets (low-trending pairs,
shorter timeframes). It struggles in strong trends — pair with a trend filter
if needed (e.g., only trade longs above the 200 SMA).
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import rsi, atr, sma


class RsiMeanReversion(Strategy):
    name = "rsi_mean_reversion"
    warmup = 50

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        rsi_period = p.get("rsi_period", 14)
        oversold    = p.get("oversold", 30)
        overbought  = p.get("overbought", 70)
        mid         = p.get("rsi_mid", 50)
        atr_period  = p.get("atr_period", 14)
        atr_mult    = p.get("atr_mult", 1.5)
        rr          = p.get("risk_reward", 2.0)
        trend_filter= p.get("trend_filter", False)  # require price > SMA200 for longs
        sma_period  = p.get("sma_period", 200)

        df = candles.copy()
        df["rsi"] = rsi(df["close"], rsi_period)
        df["atr"] = atr(df, atr_period)
        if trend_filter:
            df["sma"] = sma(df["close"], sma_period)

        if df["rsi"].iloc[-1] != df["rsi"].iloc[-1]:  # NaN guard
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        price = last["close"]
        a     = last["atr"]
        r     = last["rsi"]
        r_prev = prev["rsi"]

        # Exit open position when RSI reaches mid zone or flips
        if position and position.is_open():
            if position.side == Side.LONG and r >= mid:
                return Signal(SignalType.CLOSE, price, reason=f"rsi mid ({r:.1f})")
            if position.side == Side.SHORT and r <= mid:
                return Signal(SignalType.CLOSE, price, reason=f"rsi mid ({r:.1f})")
            return Signal(SignalType.HOLD, price, reason="holding")

        # Entry: RSI cross back through threshold
        crossed_up   = r_prev <= oversold and r > oversold   # exit oversold → long
        crossed_down = r_prev >= overbought and r < overbought  # exit overbought → short

        if crossed_up:
            if trend_filter and price < last["sma"]:
                return Signal(SignalType.HOLD, price, reason="long blocked by trend filter")
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"rsi oversold cross ({r:.1f})")

        if crossed_down:
            if trend_filter and price > last["sma"]:
                return Signal(SignalType.HOLD, price, reason="short blocked by trend filter")
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"rsi overbought cross ({r:.1f})")

        return Signal(SignalType.HOLD, price, reason="no signal")
