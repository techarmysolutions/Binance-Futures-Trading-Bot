"""
Live / paper trading engine.

Loop: pull latest closed candle → run strategy → route through RiskManager →
execute on exchange. Stops are placed ON the exchange, so a bot crash leaves
protective orders in place.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from core.exchange import BinanceFutures
from core.models import AccountState, Side, SignalType
from risk.manager import RiskManager, RiskRejection
from strategies.base import Strategy


INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}


class TradingEngine:
    def __init__(self, exchange: BinanceFutures, strategy: Strategy,
                 risk: RiskManager, pair: str, interval: str = "15m",
                 leverage: int = 3, logger: Optional[Callable[[str], None]] = None):
        self.ex = exchange
        self.strategy = strategy
        self.risk = risk
        self.pair = pair
        self.interval = interval
        self.leverage = leverage
        self._log = logger if logger else print

    def _sync_account(self) -> AccountState:
        bal = self.ex.get_balance()
        acct = AccountState(balance=bal, equity=bal, peak_equity=bal)
        pos = self.ex.get_position(self.pair)
        if pos:
            acct.open_positions[self.pair] = pos
        return acct

    def step(self) -> None:
        acct = self._sync_account()
        try:
            self.risk.check_killswitch(acct)
        except RiskRejection as e:
            self._log(f"[HALT] {e}")
            return

        df = self.ex.get_klines(self.pair, self.interval,
                                limit=self.strategy.warmup + 5)
        df = df.iloc[:-1]  # drop the still-forming candle
        pos = acct.open_positions.get(self.pair)
        signal = self.strategy.on_candle(df, pos)
        self._log(f"signal={signal.type.value} px={signal.price} :: {signal.reason}")

        if signal.type == SignalType.CLOSE and pos:
            self.ex.close_position(self.pair, pos.side, pos.quantity)
            self._log(f"  -> closed {pos.side.value} {pos.quantity}")

        elif signal.type in (SignalType.OPEN_LONG, SignalType.OPEN_SHORT) and not pos:
            try:
                sized = self.risk.size_position(signal, acct, self.leverage)
            except RiskRejection as e:
                self._log(f"  -> {e}")
                return
            side = Side.LONG if signal.type == SignalType.OPEN_LONG else Side.SHORT
            self.ex.set_leverage(self.pair, sized["leverage"])
            self.ex.open_position(self.pair, side, sized["quantity"],
                                  sized["stop_loss"], sized["take_profit"])
            self._log(f"  -> opened {side.value} qty={sized['quantity']} "
                  f"SL={sized['stop_loss']} TP={sized['take_profit']}")

    def run_forever(self) -> None:
        period = INTERVAL_SECONDS.get(self.interval, 900)
        self._log(f"Engine live on {self.pair} {self.interval} "
              f"(testnet={self.ex.testnet}). Ctrl-C to stop.")
        while True:
            try:
                self.step()
            except Exception as e:  # never let one bad tick kill the loop
                self._log(f"[ERROR] {e}")
            # sleep to just after next candle close
            now = time.time()
            time.sleep(period - (now % period) + 2)
