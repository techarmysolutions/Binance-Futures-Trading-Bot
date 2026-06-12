"""
MACD Signal Line Crossover strategy.

Logic:
  - Long  when MACD line crosses ABOVE signal line (histogram flips positive)
    AND MACD is below zero (buying into a recovery, not a parabolic top).
  - Short when MACD line crosses BELOW signal line AND MACD is above zero.
  - Optional zero-line filter (stricter): only long when MACD < 0, only short
    when MACD > 0. Disabled by default for more signals.
  - Exit: opposite MACD crossover.
  - SL: ATR-based. TP: risk:reward.

Works best on trending assets with clear momentum cycles (BTC, ETH on 1h–4h).
Generates fewer signals than EMA cross but with stronger trend confirmation.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import macd, atr


class MacdSignal(Strategy):
    name = "macd_signal"
    warmup = 60

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        fast        = p.get("macd_fast", 12)
        slow        = p.get("macd_slow", 26)
        signal_p    = p.get("macd_signal", 9)
        atr_period  = p.get("atr_period", 14)
        atr_mult    = p.get("atr_mult", 2.0)
        rr          = p.get("risk_reward", 2.0)
        zero_filter = p.get("zero_line_filter", False)

        df = candles.copy()
        df["macd"], df["sig"], df["hist"] = macd(df["close"], fast, slow, signal_p)
        df["atr"] = atr(df, atr_period)

        if df["hist"].iloc[-1] != df["hist"].iloc[-1]:
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        price = last["close"]
        a     = last["atr"]

        crossed_up   = prev["hist"] <= 0 and last["hist"] > 0   # MACD crosses above signal
        crossed_down = prev["hist"] >= 0 and last["hist"] < 0   # MACD crosses below signal

        # Exit on opposite crossover
        if position and position.is_open():
            if position.side == Side.LONG and crossed_down:
                return Signal(SignalType.CLOSE, price, reason="MACD cross down")
            if position.side == Side.SHORT and crossed_up:
                return Signal(SignalType.CLOSE, price, reason="MACD cross up")
            return Signal(SignalType.HOLD, price, reason="holding")

        if crossed_up:
            if zero_filter and last["macd"] >= 0:
                return Signal(SignalType.HOLD, price, reason="long blocked: MACD above zero")
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"MACD cross up (hist={last['hist']:.2f})")

        if crossed_down:
            if zero_filter and last["macd"] <= 0:
                return Signal(SignalType.HOLD, price, reason="short blocked: MACD below zero")
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"MACD cross down (hist={last['hist']:.2f})")

        return Signal(SignalType.HOLD, price, reason="no signal")
