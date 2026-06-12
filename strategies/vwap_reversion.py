"""
VWAP Mean Reversion strategy.

Logic:
  - VWAP is computed as a rolling session-reset VWAP (resets each UTC day).
  - Enter LONG  when price deviates below VWAP by at least (dev_threshold * ATR)
    AND RSI is in oversold territory — then reverts back toward VWAP.
  - Enter SHORT when price deviates above VWAP by at least (dev_threshold * ATR)
    AND RSI is overbought.
  - Exit: price crosses VWAP from the entry side (mean reversion complete).
  - SL: ATR-based from entry.

This strategy relies on intraday VWAP and works best on short timeframes (5m–1h)
during active trading sessions. On daily candles VWAP resets every bar so it
degrades — use RSI mean reversion instead on higher timeframes.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import vwap, atr, rsi


class VwapReversion(Strategy):
    name = "vwap_reversion"
    warmup = 50

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params
        dev_threshold = p.get("dev_threshold", 1.5)  # ATR multiples away from VWAP
        rsi_period    = p.get("rsi_period", 14)
        rsi_os        = p.get("rsi_oversold", 35)
        rsi_ob        = p.get("rsi_overbought", 65)
        atr_period    = p.get("atr_period", 14)
        atr_mult_sl   = p.get("atr_mult", 1.5)
        rr            = p.get("risk_reward", 1.5)

        df = candles.copy()
        df["vwap"] = vwap(df)
        df["atr"]  = atr(df, atr_period)
        df["rsi"]  = rsi(df["close"], rsi_period)

        if (df["vwap"].iloc[-1] != df["vwap"].iloc[-1]
                or df["atr"].iloc[-1] != df["atr"].iloc[-1]):
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last  = df.iloc[-1]
        price = last["close"]
        v     = last["vwap"]
        a     = last["atr"]
        r     = last["rsi"]

        dev = price - v   # positive = above VWAP, negative = below

        # Exit: price crosses VWAP
        if position and position.is_open():
            if position.side == Side.LONG and price >= v:
                return Signal(SignalType.CLOSE, price, reason="price returned to VWAP")
            if position.side == Side.SHORT and price <= v:
                return Signal(SignalType.CLOSE, price, reason="price returned to VWAP")
            return Signal(SignalType.HOLD, price, reason="holding")

        far_below = dev < -dev_threshold * a
        far_above = dev >  dev_threshold * a

        if far_below and r < rsi_os:
            sl = price - atr_mult_sl * a
            tp = price + atr_mult_sl * a * rr
            return Signal(SignalType.OPEN_LONG, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"below VWAP {dev:.2f} rsi={r:.1f}")

        if far_above and r > rsi_ob:
            sl = price + atr_mult_sl * a
            tp = price - atr_mult_sl * a * rr
            return Signal(SignalType.OPEN_SHORT, price,
                          stop_loss=sl, take_profit=tp,
                          reason=f"above VWAP +{dev:.2f} rsi={r:.1f}")

        return Signal(SignalType.HOLD, price, reason="no signal")
