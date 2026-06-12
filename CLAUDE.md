# Claude Code — Project Instructions

## What this project is

Binance USDⓈ-M Futures trading bot. Real money can flow through this code.
Mistakes in order logic, risk checks, or exchange calls have financial consequences.
Be conservative. Verify before changing anything in `core/`, `risk/`, or `server.py`.

---

## Critical rules

### Never bypass risk checks
`RiskManager.size_position()` and `RiskManager.check_killswitch()` are called before
every order in both live and backtest paths. Do not add shortcuts around them.
A signal without a `stop_loss` must be rejected — that is intentional.

### Never hardcode API keys
Keys live in env vars only (`BINANCE_API_KEY`, `BINANCE_API_SECRET`).
`config/settings.py` enforces this. Do not add key handling anywhere else.

### Strategy statefulness
Strategies must derive signals from the `candles` DataFrame window only.
Instance variables that persist across candles cause live/backtest divergence — avoid them.

### Backtest look-ahead
The backtester feeds `df.iloc[:i+1]` to the strategy at bar `i`.
Do not change this slice — it is the only thing preventing look-ahead bias.

---

## Project layout (quick reference)

```
core/models.py          — Signal, Position, AccountState, Side, SignalType
core/exchange.py        — All Binance REST calls; single point of exchange contact
core/engine.py          — Live loop (fetch → signal → risk → execute)
risk/manager.py         — Position sizing and kill-switches; nothing bypasses this
backtest/engine.py      — Candle replay; intrabar SL/TP fills before strategy signal
strategies/base.py      — Abstract Strategy (on_candle interface + warmup attr)
strategies/ema_cross.py — Reference implementation; use as template for new strategies
utils/indicators.py     — Pure pandas indicators; no TA-Lib dependency
config/settings.py      — Loads config.yaml + env vars; returns plain dicts / RiskConfig
server.py               — FastAPI; STATE dict holds runtime bot state (not persisted)
main.py                 — CLI; STRATEGY_REGISTRY maps name → (module, class)
web/index.html          — Single-file dashboard; no build step; talks to server.py
```

---

## Adding a strategy

1. Create `strategies/<name>.py` — subclass `Strategy`, implement `on_candle`, set `name` and `warmup`.
2. Add to `STRATEGY_REGISTRY` in `main.py`.
3. Add default params to `DEFAULT_PARAMS` in `server.py`.
4. Strategy must always return a `Signal` — never raise, never return `None`.
5. `OPEN_LONG` / `OPEN_SHORT` signals must set `stop_loss` — `RiskManager` rejects without one.

## Adding an indicator

Add a pure function to `utils/indicators.py`. Takes a `pd.Series` or `pd.DataFrame`,
returns a `pd.Series`. No side effects, no global state.

---

## Test procedure before any live change

1. Run a backtest via CLI or dashboard and verify it completes without errors.
2. Check `RiskManager.size_position()` still rejects signals missing `stop_loss`.
3. Verify `RiskManager.check_killswitch()` fires at the configured drawdown threshold.
4. If touching `core/exchange.py`, test against Binance testnet — not mainnet.

---

## Server state

`STATE` dict in `server.py` is in-memory only. Risk config changes via `POST /api/config`
reset on server restart. For permanent changes, update `config.yaml`.

`STATE["bot_stop"]` is a `threading.Event`. The bot loop checks it every candle cycle.
Call `STATE["bot_stop"].set()` to request graceful shutdown — do not `Thread.kill()`.

---

## Known constraints

- Binance klines API returns max 1500 bars per request; backtests are capped there.
- `profit_factor` returns `None` (not `inf`) when there are no losing trades — the JSON
  serialization boundary requires this; the UI renders it as ∞.
- `open_position()` in `exchange.py` calls `set_leverage(pair, 1)` internally — the caller
  must call `set_leverage` with the real value **before** `open_position`.
  See `TradingEngine.step()` for the correct call order.
- `python-binance` testnet uses a different base URL; `testnet=True` switches it automatically.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `python-binance` | Binance REST + WebSocket |
| `pandas` / `numpy` | Data manipulation and indicators |
| `pyyaml` | Config file parsing |
| `fastapi` + `uvicorn` | Dashboard API server |
| `pydantic` | Request/response validation in server.py |

No TA-Lib. No database. No message broker. Keep it that way unless there is a strong reason.
