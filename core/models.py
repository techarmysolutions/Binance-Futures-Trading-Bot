"""Core dataclasses shared across the bot."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class SignalType(str, Enum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


@dataclass
class Signal:
    """What a strategy emits each candle."""
    type: SignalType
    price: float
    # Optional strategy-supplied levels; risk manager fills gaps / overrides.
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 1.0
    reason: str = ""


@dataclass
class Position:
    pair: str
    side: Side
    entry_price: float
    quantity: float
    leverage: int
    stop_loss: float
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    opened_at: Optional[str] = None

    def is_open(self) -> bool:
        return self.side != Side.FLAT and self.quantity > 0


@dataclass
class Order:
    pair: str
    side: str            # BUY / SELL
    type: str            # MARKET / LIMIT / STOP_MARKET
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: bool = False
    client_id: str = ""


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int = 0


@dataclass
class AccountState:
    balance: float = 0.0
    equity: float = 0.0
    peak_equity: float = 0.0
    open_positions: dict = field(default_factory=dict)
