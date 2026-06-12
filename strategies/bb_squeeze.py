"""
Bollinger Band Squeeze + Breakout strategy.

Logic:
  - Detects squeeze: BB width narrows below a rolling minimum (low volatility).
  - Breakout entry: price closes outside the band after a squeeze.
    - Close above upper band → LONG
    - Close below lower band → SHORT
  - Exit: price closes back inside the opposite band (mean reversion complete)
    or ATR stop-loss is hit.
  - Momentum filter (optional): only trade breakout direction if MACD histogram
    is aligned.

Best timeframes: 15m – 4h. Works well on trending assets post-consolidation.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import bollinger, atr, macd


class BbSqueeze(Strategy):
    name = "bb_squeeze"
    warmup = 60

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        bb_period       = p.get("bb_period", 20)
        bb_std          = p.get("bb_std", 2.0)
        squeeze_window  = p.get("squeeze_window", 20)  # how many bars to measure squeeze
        atr_period      = p.get("atr_period", 14)
        atr_mult        = p.get("atr_mult", 2.0)
        rr              = p.get("risk_reward", 2.0)
        macd_filter     = p.get("macd_filter", True)

        df = candles.copy()
        upper, mid, lower = bollinger(df["close"], bb_period, bb_std)
        df["upper"] = upper
        df["mid"]   = mid
        df["lower"] = lower
        df["width"] = (upper - lower) / mid
        df["atr"]   = atr(df, atr_period)

        if macd_filter:
            _, _, df["hist"] = macd(df["close"])

        if df["width"].iloc[-1] != df["width"].iloc[-1]:  # NaN guard
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        price = last["close"]
        a     = last["atr"]

        # Exit: price reverts back inside bands or crosses mid
        if position and position.is_open():
            if position.side == Side.LONG and price < last["mid"]:
                return Signal(SignalType.CLOSE, price, reason="price < BB mid")
            if position.side == Side.SHORT and price > last["mid"]:
                return Signal(SignalType.CLOSE, price, reason="price > BB mid")
            return Signal(SignalType.HOLD, price, reason="holding")

        # Squeeze: current width below rolling minimum of past N bars
        recent_min = df["width"].iloc[-(squeeze_window + 1):-1].min()
        in_squeeze = last["width"] <= recent_min * 1.1  # 10% tolerance

        if not in_squeeze:
            return Signal(SignalType.HOLD, price, reason="no squeeze")

        above_upper = price > last["upper"]
        below_lower = price < last["lower"]

        if above_upper:
            if macd_filter and last.get("hist", 0) <= 0:
                return Signal(SignalType.HOLD, price, reason="long blocked: macd negative")
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason="BB squeeze breakout up")

        if below_lower:
            if macd_filter and last.get("hist", 0) >= 0:
                return Signal(SignalType.HOLD, price, reason="short blocked: macd positive")
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason="BB squeeze breakout down")

        return Signal(SignalType.HOLD, price, reason="no breakout")
