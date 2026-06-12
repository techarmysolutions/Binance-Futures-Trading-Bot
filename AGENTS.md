# Agents Guide

How to interact with this bot programmatically — for automated pipelines,
CI jobs, external agents, or LLM-driven trading research.

---

## HTTP API (server.py)

Start the server:
```bash
uvicorn server:app --port 8000
```

All endpoints accept and return JSON.

### Run a backtest

```bash
curl -s -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "ema_cross",
    "pair": "BTCUSDT",
    "interval": "1h",
    "limit": 1000,
    "leverage": 3,
    "start_equity": 1000,
    "params": {"ema_fast": 9, "ema_slow": 21, "atr_mult": 2.0}
  }'
```

Response shape:
```json
{
  "summary": {
    "trades": 13,
    "win_rate": 0.38,
    "return_pct": 4.21,
    "profit_factor": 1.42,
    "max_drawdown_pct": 3.1,
    "end_equity": 1042.10
  },
  "equity_curve": [1000, 1002.3, ...],
  "trades": [
    {"side": "LONG", "entry": 67200.0, "exit": 68400.0, "pnl": 12.4, "reason": "take-profit"}
  ]
}
```

`profit_factor` is `null` (no losing trades). Render as ∞.

### List strategies

```bash
curl http://localhost:8000/api/strategies
```

### Update risk config

```bash
curl -s -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "risk_per_trade": 0.01,
    "max_leverage": 5,
    "max_positions": 3,
    "daily_loss_limit": 0.05,
    "max_drawdown": 0.20,
    "min_notional": 5.0
  }'
```

### Start / stop bot

```bash
# Start paper trading
curl -s -X POST http://localhost:8000/api/bot/start \
  -H "Content-Type: application/json" \
  -d '{"mode": "paper", "strategy": "ema_cross", "pair": "BTCUSDT", "interval": "15m", "leverage": 3}'

# Poll status
curl http://localhost:8000/api/bot/status

# Stop
curl -s -X POST http://localhost:8000/api/bot/stop
```

Bot mode is `"paper"` (testnet) or `"live"` (mainnet). Live requires `BINANCE_API_KEY` and
`BINANCE_API_SECRET` set in environment. Paper also requires keys (testnet keys from
https://testnet.binancefuture.com).

---

## CLI interface (main.py)

Usable from shell scripts or subprocesses:

```bash
# Backtest — exits 0 on success, prints summary to stdout
python main.py backtest \
  --strategy ema_cross \
  --pair BTCUSDT \
  --interval 1h \
  --days 90 \
  --leverage 3

# Paper trading — runs until Ctrl-C or SIGTERM
python main.py paper --strategy ema_cross --pair BTCUSDT --interval 15m

# Live trading — prompts "I ACCEPT THE RISK" on stdin before starting
python main.py live --strategy ema_cross --pair BTCUSDT --interval 15m
```

Backtest output (stdout):
```
=== Backtest summary ===
  trades             13
  win_rate           0.385
  return_pct         4.21
  profit_factor      1.42
  max_drawdown_pct   3.1
  end_equity         1042.1
```

---

## Programmatic Python usage

### Backtest from Python

```python
from core.exchange import BinanceFutures
from backtest.engine import Backtester
from main import load_strategy
from risk.manager import RiskManager, RiskConfig

ex = BinanceFutures("x", "x", testnet=False)   # no keys needed for klines
df = ex.get_klines("BTCUSDT", "1h", limit=500)

strat = load_strategy("ema_cross", {"ema_fast": 9, "ema_slow": 21})
risk = RiskManager(RiskConfig(risk_per_trade=0.01, max_leverage=5))
bt = Backtester(strat, risk, start_equity=1000, leverage=3)
result = bt.run(df, "BTCUSDT")

print(result.summary())
# result.trades   — list of Trade(side, entry, exit, qty, pnl, reason)
# result.equity_curve  — list[float], one value per bar after warmup
```

### Build and run a custom strategy

```python
import pandas as pd
from strategies.base import Strategy
from core.models import Signal, SignalType

class MyStrategy(Strategy):
    name = "my_strategy"
    warmup = 30

    def on_candle(self, candles: pd.DataFrame, position) -> Signal:
        price = candles["close"].iloc[-1]
        # your logic here
        return Signal(SignalType.HOLD, price, reason="no signal")
```

Pass it directly to `Backtester(strat, risk)` — no registration needed for Python use.

---

## Parameter sweep example

Run multiple backtests to find better EMA periods:

```python
from itertools import product
from core.exchange import BinanceFutures
from backtest.engine import Backtester
from main import load_strategy
from risk.manager import RiskManager, RiskConfig

ex = BinanceFutures("x", "x", testnet=False)
df = ex.get_klines("BTCUSDT", "1h", limit=1000)

results = []
for fast, slow in product([5, 9, 12], [21, 50, 100]):
    if fast >= slow:
        continue
    strat = load_strategy("ema_cross", {"ema_fast": fast, "ema_slow": slow})
    risk = RiskManager(RiskConfig())
    bt = Backtester(strat, risk, start_equity=1000, leverage=3)
    r = bt.run(df, "BTCUSDT")
    s = r.summary()
    results.append({"fast": fast, "slow": slow, **s})

# sort by return
results.sort(key=lambda x: x["return_pct"], reverse=True)
for r in results[:5]:
    print(r)
```

---

## Automation notes

- **No authentication** on the HTTP API. Run behind a firewall or bind to `127.0.0.1`.
- **State is in-memory.** Risk config changes via API reset on server restart. For persistent config, edit `config.yaml`.
- **One bot instance per server process.** The server does not support multiple concurrent bots on different pairs. For multi-pair operation, run multiple server processes on different ports.
- **Log polling.** `GET /api/bot/status` returns the last 50 log lines. Poll at your candle interval or slower — no WebSocket push yet.
- **Kline limit.** Binance returns max 1500 bars per request. For longer backtests, implement a pagination loop around `ex.get_klines()`.
