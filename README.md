# Binance Futures Trading Bot

Modular, risk-first algorithmic trading bot for Binance USDⓈ-M Futures.
Comes with a browser dashboard, CLI, event-driven backtester, and pluggable strategy API.

## Design principles

1. **Risk first.** No order leaves without a stop-loss and a position-size check through `RiskManager`.
2. **Pluggable strategies.** One file in `strategies/`, one method to implement — done.
3. **Backtest before live.** Backtester and live engine share the same `Strategy` and `RiskManager` instances; no divergence.
4. **No secrets in code.** API keys come from env vars only — never from config files.
5. **Crash-safe stops.** Protective STOP_MARKET orders are placed on the exchange at entry, not managed in-process. A crashed bot still has downside protection sitting on Binance.

---

## Architecture

```
futures-bot/
├── core/
│   ├── exchange.py       # Binance USDⓈ-M Futures REST connector (python-binance wrapper)
│   ├── engine.py         # Live/paper loop: fetch → signal → risk → execute
│   └── models.py         # Signal, Position, Order, AccountState, Side, SignalType dataclasses
├── strategies/
│   ├── base.py           # Abstract Strategy — implement on_candle() and set warmup
│   └── ema_cross.py      # EMA crossover + RSI filter + ATR stop-loss (template strategy)
├── risk/
│   └── manager.py        # Position sizing, leverage cap, daily loss limit, drawdown kill-switch
├── backtest/
│   └── engine.py         # Candle-by-candle backtester (no look-ahead, intrabar SL/TP fills)
├── config/
│   └── settings.py       # Loads config.yaml + env vars; builds RiskConfig
├── utils/
│   └── indicators.py     # EMA, SMA, RSI, ATR, MACD, Bollinger Bands (pure pandas, no TA-Lib)
├── web/
│   └── index.html        # Single-file dark dashboard (no build step)
├── server.py             # FastAPI backend — wraps all bot logic for the dashboard
├── main.py               # CLI entrypoint (backtest / paper / live subcommands)
├── requirements.txt
├── config.example.yaml
└── .env.example
```

### Data flow

```
Binance REST
    │  klines (OHLCV)
    ▼
Strategy.on_candle()
    │  Signal (type, price, stop_loss, take_profit)
    ▼
RiskManager.size_position()
    │  sized order dict  (or RiskRejection)
    ▼
TradingEngine / Backtester
    │  market order + STOP_MARKET + TAKE_PROFIT_MARKET
    ▼
Binance REST (live) / simulated fill (backtest)
```

---

## Quick start

### Browser dashboard (recommended)

```bash
pip install -r requirements.txt
# Windows:
uvicorn server:app --port 8000
# macOS/Linux:
./run_ui.sh
```

Open **http://localhost:8000**

No API keys needed for backtesting — it uses public kline endpoints.

### CLI

```bash
# Backtest last 90 days of BTCUSDT 1h candles
python main.py backtest --strategy ema_cross --pair BTCUSDT --interval 1h --days 90

# Paper trading (Binance testnet)
python main.py paper --strategy ema_cross --pair BTCUSDT --interval 15m

# Live trading (real money — requires explicit confirmation prompt)
python main.py live --strategy ema_cross --pair BTCUSDT --interval 15m
```

---

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit risk params
cp .env.example .env                  # add API keys
```

### Environment variables

| Variable | Required for |
|----------|-------------|
| `BINANCE_API_KEY` | paper trading, live trading |
| `BINANCE_API_SECRET` | paper trading, live trading |

Backtesting requires **no keys** — public kline data only.

---

## Dashboard features

| Tab | What it does |
|-----|-------------|
| **Backtest** | Choose strategy / pair / interval / leverage / bars, run, view equity curve + metrics + trade table |
| **Run Bot** | Start/stop in paper or live mode; live log stream; status LED |
| **Risk Controls** | Edit `risk_per_trade`, `max_leverage`, `daily_loss_limit`, `max_drawdown` without restart |

---

## Risk controls

All configured in `config.yaml` under `risk:` or via the dashboard panel.

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `risk_per_trade` | `0.01` | Fraction of equity risked per trade (1%) |
| `max_leverage` | `5` | Hard leverage cap — strategy cannot exceed this |
| `max_positions` | `3` | Max concurrent open positions |
| `daily_loss_limit` | `0.05` | Halt trading after -5% on the day |
| `max_drawdown` | `0.20` | Kill-switch at -20% from peak equity |
| `min_notional` | `5.0` | Minimum order size in USDT (Binance minimum) |

Kill-switch is checked on every candle **before** any order is placed.
When triggered, `RiskManager.halted = True` and no new orders are accepted until `reset_day()` is called.

---

## Writing a new strategy

1. Create `strategies/my_strategy.py`:

```python
from strategies.base import Strategy
from core.models import Position, Signal, SignalType

class MyStrategy(Strategy):
    name = "my_strategy"
    warmup = 50  # candles needed before first signal

    def on_candle(self, candles, position):
        # candles: pd.DataFrame with columns open_time, open, high, low, close, volume
        # position: Position | None
        price = candles["close"].iloc[-1]
        # ... your logic ...
        return Signal(SignalType.HOLD, price, reason="no signal")
```

2. Register it in `main.py`:

```python
STRATEGY_REGISTRY = {
    "ema_cross": ("strategies.ema_cross", "EmaCross"),
    "my_strategy": ("strategies.my_strategy", "MyStrategy"),   # add this
}
```

3. Add default params to `server.py` `DEFAULT_PARAMS` dict so the dashboard exposes them.

**Rules for strategies:**
- Must be stateless — derive everything from the `candles` window, not instance vars.
- Must always return a `Signal` (never `None`, never raise).
- Stop-loss is **mandatory** on `OPEN_LONG` / `OPEN_SHORT` signals; `RiskManager` rejects without one.

---

## Available indicators (`utils/indicators.py`)

| Function | Signature |
|----------|-----------|
| `ema(series, period)` | Exponential moving average |
| `sma(series, period)` | Simple moving average |
| `rsi(series, period=14)` | RSI (0–100) |
| `atr(df, period=14)` | Average True Range (needs high/low/close columns) |
| `macd(series, fast, slow, signal)` | Returns `(macd_line, signal_line, histogram)` |
| `bollinger(series, period, std)` | Returns `(upper, mid, lower)` |

---

## Backtester details

- **No look-ahead bias** — strategy receives only `candles.iloc[:i+1]` at bar `i`.
- **Intrabar SL/TP** — stop-loss and take-profit are checked against the candle's high/low before the strategy signal is evaluated.
- **Fee model** — 0.04% per fill (Binance futures taker fee) applied on entry and exit.
- **Same risk sizing as live** — `RiskManager.size_position()` is called identically in both modes.
- **profit_factor** returns `None` (shown as ∞ in UI) when there are zero losing trades.

---

## API reference (server.py)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/api/strategies` | List strategies and default params |
| `POST` | `/api/backtest` | Run backtest; returns summary + equity curve + trades |
| `GET` | `/api/config` | Current risk config |
| `POST` | `/api/config` | Update risk config (in-memory, resets on restart) |
| `POST` | `/api/bot/start` | Start engine in background thread |
| `POST` | `/api/bot/stop` | Stop running engine |
| `GET` | `/api/bot/status` | Running state + last 50 log lines + account snapshot |

---

## Risk warning

Leveraged futures can lose more than your deposit. The default EMA cross strategy
is a **template**, not a profitable edge — backtest and tune on testnet before
risking real capital. This software is provided as-is with no guarantee of profit.
Start on testnet (`paper` mode), use minimum position sizes, and never disable
the stop-loss or kill-switch.
