"""Strategy interface. Every strategy subclasses this and implements `on_candle`."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from core.models import Position, Signal


class Strategy(ABC):
    """
    A strategy receives a DataFrame of recent candles (columns:
    open_time, open, high, low, close, volume) plus the current open
    position (or None) and returns exactly one Signal.

    Strategies must be STATELESS where possible — derive everything from
    the candle window so backtest and live behave identically.
    """

    name: str = "base"
    # How many candles of history the strategy needs before it can decide.
    warmup: int = 50

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def on_candle(self, candles: pd.DataFrame, position: Position | None) -> Signal:
        ...

    def __repr__(self) -> str:
        return f"<Strategy {self.name} params={self.params}>"
