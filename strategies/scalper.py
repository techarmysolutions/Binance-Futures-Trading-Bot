"""
Scalping strategy using fast EMA crosses with RSI confirmation.
Designed for 1m-5m timeframes for quick entries and exits.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import atr, ema, rsi


class Scalper(Strategy):
    name = "scalper"
    warmup = 50

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params

        ema_fast = int(p.get("ema_fast", 8))
        ema_slow = int(p.get("ema_slow", 21))
        rsi_period = int(p.get("rsi_period", 14))
        rsi_ob = float(p.get("rsi_overbought", 70))
        rsi_os = float(p.get("rsi_oversold", 30))
        atr_period = int(p.get("atr_period", 14))
        atr_mult = float(p.get("atr_mult", 1.5))
        rr = float(p.get("risk_reward", 1.5))

        df = candles.copy()
        df["ema_fast"] = ema(df["close"], ema_fast)
        df["ema_slow"] = ema(df["close"], ema_slow)
        df["rsi"] = rsi(df["close"], rsi_period)
        df["atr"] = atr(df, atr_period)

        if len(df) < self.warmup:
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        last = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(last["close"])
        ema_f = float(last["ema_fast"])
        ema_s = float(last["ema_slow"])
        rsi_val = float(last["rsi"])
        a = float(last["atr"])

        # Check if we have a position to manage
        if position and position.is_open():
            # Tight stop-loss for scalping
            sl_distance = atr_mult * a

            if position.side == Side.LONG:
                # Take profit at 1.5x ATR or tighter
                tp = price + sl_distance * rr
                # Move stop to breakeven + small profit after 0.5%
                if price > position.entry_price * 1.003:
                    new_sl = max(position.entry_price * 1.002, price - sl_distance * 0.5)
                    return Signal(
                        SignalType.CLOSE, price, stop_loss=new_sl, take_profit=tp,
                        reason="scalp exit"
                    )
            else:  # SHORT
                tp = price - sl_distance * rr
                if price < position.entry_price * 0.997:
                    new_sl = min(position.entry_price * 1.002, price + sl_distance * 0.5)
                    return Signal(
                        SignalType.CLOSE, price, stop_loss=new_sl, take_profit=tp,
                        reason="scalp exit"
                    )
            return Signal(SignalType.HOLD, price, reason="holding")

        # Entry signals
        prev_fast = float(prev["ema_fast"])
        prev_slow = float(prev["ema_slow"])
        prev_close = float(prev["close"])

        # Bullish cross: fast crosses above slow
        bullish_cross = prev_fast <= prev_slow and ema_f > ema_s
        # Bearish cross: fast crosses below slow
        bearish_cross = prev_fast >= prev_slow and ema_f < ema_s

        # Long entry: bullish cross + RSI not overbought
        if bullish_cross and rsi_val < rsi_ob and rsi_val > 35:
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(
                SignalType.OPEN_LONG, price, stop_loss=sl, take_profit=tp,
                reason=f"EMA cross up RSI={rsi_val:.1f}"
            )

        # Short entry: bearish cross + RSI not oversold
        if bearish_cross and rsi_val > rsi_os and rsi_val < 65:
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(
                SignalType.OPEN_SHORT, price, stop_loss=sl, take_profit=tp,
                reason=f"EMA cross down RSI={rsi_val:.1f}"
            )

        return Signal(SignalType.HOLD, price, reason="no signal")
