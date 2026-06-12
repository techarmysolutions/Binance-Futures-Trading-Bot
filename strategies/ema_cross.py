"""
Example strategy: EMA crossover with RSI filter and ATR-based stop-loss.

Logic:
  - Long  when fast EMA crosses ABOVE slow EMA and RSI < overbought.
  - Short when fast EMA crosses BELOW slow EMA and RSI > oversold.
  - Stop-loss placed at entry +/- (atr_mult * ATR).
  - Take-profit at risk:reward ratio defined in params.

This is a TEMPLATE, not a profitable edge. Backtest and tune before using.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import ema, rsi, atr


class EmaCross(Strategy):
    name = "ema_cross"
    warmup = 60

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        fast = p.get("ema_fast", 9)
        slow = p.get("ema_slow", 21)
        rsi_period = p.get("rsi_period", 14)
        rsi_ob = p.get("rsi_overbought", 70)
        rsi_os = p.get("rsi_oversold", 30)
        atr_period = p.get("atr_period", 14)
        atr_mult = p.get("atr_mult", 2.0)
        rr = p.get("risk_reward", 2.0)

        df = candles.copy()
        df["ema_fast"] = ema(df["close"], fast)
        df["ema_slow"] = ema(df["close"], slow)
        df["rsi"] = rsi(df["close"], rsi_period)
        df["atr"] = atr(df, atr_period)

        if len(df) < self.warmup or df["atr"].iloc[-1] != df["atr"].iloc[-1]:  # NaN guard
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last, prev = df.iloc[-1], df.iloc[-2]
        price = last["close"]
        a = last["atr"]

        crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
        crossed_dn = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]

        # Exit logic if in a position and the trend flips against it.
        if position and position.is_open():
            if position.side == Side.LONG and crossed_dn:
                return Signal(SignalType.CLOSE, price, reason="ema flip down")
            if position.side == Side.SHORT and crossed_up:
                return Signal(SignalType.CLOSE, price, reason="ema flip up")
            return Signal(SignalType.HOLD, price, reason="holding")

        # Entry logic when flat.
        if crossed_up and last["rsi"] < rsi_ob:
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(SignalType.OPEN_LONG, price, stop_loss=sl,
                          take_profit=tp, reason="ema cross up + rsi ok")

        if crossed_dn and last["rsi"] > rsi_os:
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(SignalType.OPEN_SHORT, price, stop_loss=sl,
                          take_profit=tp, reason="ema cross down + rsi ok")

        return Signal(SignalType.HOLD, price, reason="no signal")
