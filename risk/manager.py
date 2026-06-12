"""
Risk manager — the single gatekeeper between a strategy signal and a real order.

NOTHING bypasses this. It enforces:
  - mandatory stop-loss on every position
  - position sizing by % account risk per trade
  - max leverage cap
  - max concurrent positions
  - daily loss limit + max drawdown kill-switch
"""
from __future__ import annotations

from dataclasses import dataclass

from core.models import AccountState, Signal, SignalType


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01      # 1% of equity risked per trade
    max_leverage: int = 5
    max_positions: int = 3
    daily_loss_limit: float = 0.05    # halt after -5% day
    max_drawdown: float = 0.20        # kill-switch at -20% from peak equity
    min_notional: float = 5.0         # Binance min order notional (USDT)


class RiskRejection(Exception):
    pass


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.cfg = config
        self.day_start_equity: float | None = None
        self.halted = False

    # ---- kill-switches -------------------------------------------------
    def check_killswitch(self, acct: AccountState) -> None:
        if acct.peak_equity and acct.equity / acct.peak_equity - 1 <= -self.cfg.max_drawdown:
            self.halted = True
            raise RiskRejection(
                f"KILL-SWITCH: drawdown breached {self.cfg.max_drawdown:.0%}"
            )
        if self.day_start_equity is None:
            self.day_start_equity = acct.equity
        if self.day_start_equity and acct.equity / self.day_start_equity - 1 <= -self.cfg.daily_loss_limit:
            self.halted = True
            raise RiskRejection(
                f"DAILY LOSS LIMIT hit ({self.cfg.daily_loss_limit:.0%}) — trading paused"
            )

    def reset_day(self, acct: AccountState) -> None:
        self.day_start_equity = acct.equity
        self.halted = False

    # ---- position sizing ----------------------------------------------
    def size_position(self, signal: Signal, acct: AccountState, leverage: int) -> dict:
        """Return dict with quantity, leverage, stop_loss, take_profit — or raise."""
        if self.halted:
            raise RiskRejection("Trading halted by kill-switch")

        if signal.type not in (SignalType.OPEN_LONG, SignalType.OPEN_SHORT):
            raise RiskRejection("size_position called on non-entry signal")

        if signal.stop_loss is None:
            raise RiskRejection("REJECTED: no stop-loss on entry signal")

        if len(acct.open_positions) >= self.cfg.max_positions:
            raise RiskRejection(
                f"REJECTED: max positions ({self.cfg.max_positions}) reached"
            )

        lev = min(leverage, self.cfg.max_leverage)
        entry = signal.price
        risk_per_unit = abs(entry - signal.stop_loss)
        if risk_per_unit <= 0:
            raise RiskRejection("REJECTED: stop-loss equals entry")

        risk_capital = acct.equity * self.cfg.risk_per_trade
        quantity = risk_capital / risk_per_unit

        notional = quantity * entry
        # Cap by available margin given leverage.
        max_notional = acct.balance * lev
        if notional > max_notional:
            quantity = max_notional / entry
            notional = quantity * entry

        if notional < self.cfg.min_notional:
            raise RiskRejection(
                f"REJECTED: notional {notional:.2f} below min {self.cfg.min_notional}"
            )

        return {
            "quantity": round(quantity, 6),
            "leverage": lev,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "notional": round(notional, 2),
            "risk_capital": round(risk_capital, 2),
        }
