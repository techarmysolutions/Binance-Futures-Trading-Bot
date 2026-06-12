"""
VRVP + POC + VWAP strategy.

Volume Profile (VRVP) gives static high-volume price levels; VWAP gives a
dynamic intraday fair-value anchor. Requiring both to agree filters low-quality
setups and raises hit-rate at the cost of fewer signals.

Levels computed each candle:
  POC  — price with highest traded volume in the visible range
  VAH  — Value Area High  (upper bound of 70 % volume zone around POC)
  VAL  — Value Area Low   (lower bound of 70 % volume zone around POC)
  VWAP — session-reset volume-weighted average price

────────────────────────────────────────────────────────────────────────────
mode = "reversion"  (default)
  Long  — price crosses above VAL from below
           + price < VWAP  (discounted vs fair value — high-probability reversal)
           + RSI not overbought
  Short — price crosses below VAH from above
           + price > VWAP  (premium vs fair value)
           + RSI not oversold
  Exit  — price reaches POC  OR  price crosses VWAP (whichever first)
  SL    — ATR-based

mode = "breakout"
  Long  — close breaks above VAH
           + price > VWAP  (momentum confirmed by VWAP positioning)
           + RSI not overbought
  Short — close breaks below VAL
           + price < VWAP
           + RSI not oversold
  Exit  — price closes back inside Value Area  OR  VWAP flips against position
  SL    — ATR-based, TP — risk:reward based

Set vwap_filter = false to disable the VWAP confluence check (reverts to pure
VRVP/POC signals — useful on daily+ where session VWAP is less meaningful).

Tuning notes:
  - vp_period 200, num_bins 200 matches TradingView VRVP Row Size 200.
  - Value area always 70 % — matches standard VRVP setting.
  - 15m–4h works best; on daily+ set vwap_filter=false.
  - In reversion mode tighten risk_reward if POC is close to entry.
  - In breakout mode widen atr_mult to reduce noise at VAH/VAL.
"""
from __future__ import annotations

import pandas as pd

from core.models import Position, Signal, SignalType, Side
from strategies.base import Strategy
from utils.indicators import atr, rsi, vwap, volume_profile_poc


class VrvpPoc(Strategy):
    name   = "vrvp_poc"
    warmup = 220

    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        p = self.params

        vp_period    = int(p.get("vp_period",       200))
        num_bins     = int(p.get("num_bins",         200))
        mode         = str(p.get("mode",       "reversion"))  # "reversion" | "breakout"
        vwap_filter  = bool(p.get("vwap_filter",    True))
        rsi_period   = int(p.get("rsi_period",        14))
        rsi_ob       = float(p.get("rsi_overbought",  70))
        rsi_os       = float(p.get("rsi_oversold",    30))
        atr_period   = int(p.get("atr_period",        14))
        atr_mult     = float(p.get("atr_mult",        2.0))
        rr           = float(p.get("risk_reward",     2.0))

        df = candles.copy()
        df["atr"]  = atr(df, atr_period)
        df["rsi"]  = rsi(df["close"], rsi_period)
        df["vwap"] = vwap(df)

        min_bars = max(self.warmup, vp_period + 1)
        last_atr  = df["atr"].iloc[-1]
        last_vwap = df["vwap"].iloc[-1]
        if len(df) < min_bars or last_atr != last_atr or last_vwap != last_vwap:
            return Signal(SignalType.HOLD, df["close"].iloc[-1], reason="warmup")

        poc, vah, val = volume_profile_poc(df, vp_period, num_bins)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        price = float(last["close"])
        a     = float(last["atr"])
        r     = float(last["rsi"])
        v     = float(last["vwap"])

        if mode == "breakout":
            return self._breakout(
                position, prev, price, a, r, v,
                poc, vah, val, rsi_ob, rsi_os, atr_mult, rr, vwap_filter,
            )
        return self._reversion(
            position, prev, price, a, r, v,
            poc, vah, val, rsi_ob, rsi_os, atr_mult, rr, vwap_filter,
        )

    # ------------------------------------------------------------------
    def _reversion(
        self, position, prev, price, a, r, v,
        poc, vah, val, rsi_ob, rsi_os, atr_mult, rr, vwap_filter,
    ) -> Signal:
        if position and position.is_open():
            # Exit at POC (mean-reversion target) or when VWAP flips in favour
            if position.side == Side.LONG:
                if price >= poc:
                    return Signal(SignalType.CLOSE, price, reason="reached POC")
                if price >= v:
                    return Signal(SignalType.CLOSE, price, reason="crossed above VWAP")
            if position.side == Side.SHORT:
                if price <= poc:
                    return Signal(SignalType.CLOSE, price, reason="reached POC")
                if price <= v:
                    return Signal(SignalType.CLOSE, price, reason="crossed below VWAP")
            return Signal(SignalType.HOLD, price, reason="holding")

        crossed_above_val = float(prev["close"]) < val and price > val
        crossed_below_vah = float(prev["close"]) > vah and price < vah

        # VWAP confluence: long only below VWAP, short only above VWAP
        long_vwap_ok  = (price < v) if vwap_filter else True
        short_vwap_ok = (price > v) if vwap_filter else True

        if crossed_above_val and r < rsi_ob and long_vwap_ok:
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(
                SignalType.OPEN_LONG, price, stop_loss=sl, take_profit=tp,
                reason=f"VAL bounce {val:.4f} below VWAP {v:.4f} → POC {poc:.4f}",
            )

        if crossed_below_vah and r > rsi_os and short_vwap_ok:
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(
                SignalType.OPEN_SHORT, price, stop_loss=sl, take_profit=tp,
                reason=f"VAH reject {vah:.4f} above VWAP {v:.4f} → POC {poc:.4f}",
            )

        return Signal(SignalType.HOLD, price, reason="no signal")

    def _breakout(
        self, position, prev, price, a, r, v,
        poc, vah, val, rsi_ob, rsi_os, atr_mult, rr, vwap_filter,
    ) -> Signal:
        if position and position.is_open():
            # Exit when price falls back inside VA or VWAP flips against position
            if position.side == Side.LONG:
                if price < vah:
                    return Signal(SignalType.CLOSE, price, reason="back inside VA")
                if price < v:
                    return Signal(SignalType.CLOSE, price, reason="dropped below VWAP")
            if position.side == Side.SHORT:
                if price > val:
                    return Signal(SignalType.CLOSE, price, reason="back inside VA")
                if price > v:
                    return Signal(SignalType.CLOSE, price, reason="rose above VWAP")
            return Signal(SignalType.HOLD, price, reason="holding")

        broke_above_vah = float(prev["close"]) <= vah and price > vah
        broke_below_val = float(prev["close"]) >= val and price < val

        # VWAP confluence: long only above VWAP, short only below VWAP
        long_vwap_ok  = (price > v) if vwap_filter else True
        short_vwap_ok = (price < v) if vwap_filter else True

        if broke_above_vah and r < rsi_ob and long_vwap_ok:
            sl = price - atr_mult * a
            tp = price + atr_mult * a * rr
            return Signal(
                SignalType.OPEN_LONG, price, stop_loss=sl, take_profit=tp,
                reason=f"breakout above VAH {vah:.4f} + above VWAP {v:.4f}",
            )

        if broke_below_val and r > rsi_os and short_vwap_ok:
            sl = price + atr_mult * a
            tp = price - atr_mult * a * rr
            return Signal(
                SignalType.OPEN_SHORT, price, stop_loss=sl, take_profit=tp,
                reason=f"breakdown below VAL {val:.4f} + below VWAP {v:.4f}",
            )

        return Signal(SignalType.HOLD, price, reason="no signal")
