"""Lightweight technical indicators (pure pandas/numpy, no TA-Lib needed)."""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — used for volatility-based stops."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    mid = sma(series, period)
    dev = series.rolling(window=period).std()
    return mid + std * dev, mid, mid - std * dev


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Supertrend: returns +1 (uptrend) or -1 (downtrend) for each bar.

    Bands stored in trend.attrs['upper'] and trend.attrs['lower'] for use as stops.
    """
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, period)
    upper_basic = (hl2 + multiplier * a).values
    lower_basic = (hl2 - multiplier * a).values
    close = df["close"].values
    n = len(df)

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    trend = [1] * n

    # Find first valid (non-NaN) bar to start the iteration
    first_valid = period  # ATR needs 'period' bars
    for i in range(first_valid, n):
        # Final upper band: only tighten, reset when price was above it
        if not (upper_basic[i] == upper_basic[i]):  # NaN check
            upper[i] = upper[i - 1]
        elif upper_basic[i] < upper[i - 1] or close[i - 1] > upper[i - 1]:
            upper[i] = upper_basic[i]
        else:
            upper[i] = upper[i - 1]

        # Final lower band: only raise, reset when price was below it
        if not (lower_basic[i] == lower_basic[i]):  # NaN check
            lower[i] = lower[i - 1]
        elif lower_basic[i] > lower[i - 1] or close[i - 1] < lower[i - 1]:
            lower[i] = lower_basic[i]
        else:
            lower[i] = lower[i - 1]

        # Trend direction
        if trend[i - 1] == -1 and close[i] > upper[i]:
            trend[i] = 1
        elif trend[i - 1] == 1 and close[i] < lower[i]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

    idx = df.index
    result = pd.Series(trend, index=idx, dtype=int)
    result.attrs["upper"] = pd.Series(upper, index=idx)
    result.attrs["lower"] = pd.Series(lower, index=idx)
    return result


def volume_profile_poc(df: pd.DataFrame, period: int = 100, num_bins: int = 50):
    """
    Visible Range Volume Profile over the last `period` bars.

    Returns (poc, vah, val):
      poc — Point of Control: price level with highest traded volume
      vah — Value Area High: upper bound of the zone containing 70 % of volume
      val — Value Area Low:  lower bound of the same zone

    Volume is distributed evenly across every price bin a candle's high-low
    range overlaps, which approximates how most charting platforms render VRVP.
    """
    import numpy as np

    window = df.tail(period)
    lo = window["low"].min()
    hi = window["high"].max()
    if hi <= lo:
        mid = (hi + lo) / 2.0
        return mid, mid, mid

    edges = np.linspace(lo, hi, num_bins + 1)
    bin_vol = np.zeros(num_bins)

    for _, row in window.iterrows():
        bar_lo = row["low"]
        bar_hi = row["high"]
        vol    = row["volume"]
        lo_i   = max(0, np.searchsorted(edges, bar_lo, side="left") - 1)
        hi_i   = min(num_bins - 1, np.searchsorted(edges, bar_hi, side="right") - 1)
        count  = hi_i - lo_i + 1
        if count > 0:
            bin_vol[lo_i:hi_i + 1] += vol / count

    poc_i = int(np.argmax(bin_vol))
    poc   = (edges[poc_i] + edges[poc_i + 1]) / 2.0

    # Expand value area outward from POC until 70 % of volume is enclosed.
    total       = bin_vol.sum()
    target      = total * 0.70
    accumulated = bin_vol[poc_i]
    lo_i, hi_i  = poc_i, poc_i

    while accumulated < target:
        add_lo = bin_vol[lo_i - 1] if lo_i > 0 else 0.0
        add_hi = bin_vol[hi_i + 1] if hi_i < num_bins - 1 else 0.0
        if add_lo == 0.0 and add_hi == 0.0:
            break
        if add_lo >= add_hi and lo_i > 0:
            lo_i -= 1
            accumulated += bin_vol[lo_i]
        elif hi_i < num_bins - 1:
            hi_i += 1
            accumulated += bin_vol[hi_i]
        else:
            break

    val = (edges[lo_i] + edges[lo_i + 1]) / 2.0
    vah = (edges[hi_i] + edges[hi_i + 1]) / 2.0
    return poc, vah, val


def vwap(df: pd.DataFrame) -> pd.Series:
    """Rolling session VWAP — resets on each new calendar day (UTC)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"]
    cumvol = pd.Series(dtype=float, index=df.index)
    cumtpv = pd.Series(dtype=float, index=df.index)

    # Handle open_time - may be in ms or as datetime string
    if "open_time" in df.columns:
        try:
            dates = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.date
        except Exception:
            # Fallback: use close_time or just never reset
            dates = None
    else:
        dates = None

    cum_v = 0.0
    cum_tv = 0.0
    prev_date = None
    for i in df.index:
        if dates is not None:
            d = dates[i]
            if d != prev_date:
                cum_v = 0.0
                cum_tv = 0.0
                prev_date = d
        cum_v += vol[i]
        cum_tv += typical[i] * vol[i]
        cumvol[i] = cum_v
        cumtpv[i] = cum_tv

    return cumtpv / cumvol.replace(0, float("nan"))
