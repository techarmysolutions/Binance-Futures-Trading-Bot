"""
Vectorless event-driven backtester. Replays candles one at a time so the
strategy sees exactly what it would see live (no look-ahead bias).

Models: fees, stop-loss/take-profit fills intrabar, and the same RiskManager
sizing used in live trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core.models import AccountState, Position, Side, Signal, SignalType
from risk.manager import RiskManager, RiskRejection
from strategies.base import Strategy


@dataclass
class Trade:
    side: str
    entry: float
    exit: float
    qty: float
    pnl: float
    reason: str


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    start_equity: float = 0.0
    end_equity: float = 0.0

    def summary(self) -> dict:
        n = len(self.trades)
        wins = [t for t in self.trades if t.pnl > 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl <= 0)
        peak = self.start_equity
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak else 0)
        return {
            "trades": n,
            "win_rate": round(len(wins) / n, 3) if n else 0,
            "return_pct": round((self.end_equity / self.start_equity - 1) * 100, 2)
            if self.start_equity else 0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "max_drawdown_pct": round(max_dd * 100, 2),
            "end_equity": round(self.end_equity, 2),
        }


class Backtester:
    def __init__(self, strategy: Strategy, risk: RiskManager,
                 start_equity: float = 1000.0, fee: float = 0.0004,
                 leverage: int = 3):
        self.strategy = strategy
        self.risk = risk
        self.fee = fee
        self.leverage = leverage
        self.acct = AccountState(balance=start_equity, equity=start_equity,
                                  peak_equity=start_equity)
        self.start_equity = start_equity

    def run(self, df: pd.DataFrame, pair: str = "BTCUSDT") -> BacktestResult:
        result = BacktestResult(start_equity=self.start_equity)
        pos: Position | None = None
        warmup = self.strategy.warmup

        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            candle = df.iloc[i]

            # Intrabar SL/TP check first (priority: stop before signal).
            if pos and pos.is_open():
                hit = self._check_exit(pos, candle)
                if hit:
                    exit_px, reason = hit
                    pnl = self._pnl(pos, exit_px)
                    self.acct.equity += pnl
                    self.acct.balance += pnl
                    result.trades.append(Trade(pos.side.value, pos.entry_price,
                                               exit_px, pos.quantity, pnl, reason))
                    self.acct.open_positions.pop(pair, None)
                    pos = None

            signal = self.strategy.on_candle(window, pos)

            if signal.type == SignalType.CLOSE and pos and pos.is_open():
                pnl = self._pnl(pos, candle["close"])
                self.acct.equity += pnl
                self.acct.balance += pnl
                result.trades.append(Trade(pos.side.value, pos.entry_price,
                                           candle["close"], pos.quantity, pnl, signal.reason))
                self.acct.open_positions.pop(pair, None)
                pos = None

            elif signal.type in (SignalType.OPEN_LONG, SignalType.OPEN_SHORT) and not pos:
                try:
                    self.risk.check_killswitch(self.acct)
                    sized = self.risk.size_position(signal, self.acct, self.leverage)
                except RiskRejection:
                    result.equity_curve.append(self.acct.equity)
                    continue
                side = Side.LONG if signal.type == SignalType.OPEN_LONG else Side.SHORT
                fee_cost = sized["notional"] * self.fee
                self.acct.equity -= fee_cost
                self.acct.balance -= fee_cost
                pos = Position(pair, side, signal.price, sized["quantity"],
                               sized["leverage"], sized["stop_loss"], sized["take_profit"])
                self.acct.open_positions[pair] = pos

            self.acct.peak_equity = max(self.acct.peak_equity, self.acct.equity)
            result.equity_curve.append(self.acct.equity)

        result.end_equity = self.acct.equity
        return result

    def _check_exit(self, pos: Position, candle) -> tuple[float, str] | None:
        if pos.side == Side.LONG:
            if candle["low"] <= pos.stop_loss:
                return pos.stop_loss, "stop-loss"
            if pos.take_profit and candle["high"] >= pos.take_profit:
                return pos.take_profit, "take-profit"
        else:
            if candle["high"] >= pos.stop_loss:
                return pos.stop_loss, "stop-loss"
            if pos.take_profit and candle["low"] <= pos.take_profit:
                return pos.take_profit, "take-profit"
        return None

    def _pnl(self, pos: Position, exit_px: float) -> float:
        direction = 1 if pos.side == Side.LONG else -1
        gross = (exit_px - pos.entry_price) * direction * pos.quantity
        return gross - exit_px * pos.quantity * self.fee
