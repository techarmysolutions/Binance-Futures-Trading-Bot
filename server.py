"""
FastAPI server — exposes the bot to the browser UI.

Endpoints:
  GET  /                     -> dashboard (static index.html)
  GET  /api/strategies       -> list available strategies + default params
  POST /api/backtest         -> run a backtest, return metrics + equity curve + trades
  GET  /api/config           -> current risk config
  POST /api/config           -> update risk config and persist to config.yaml
  GET  /api/ui-state         -> last saved UI form state (restored on page load)
  POST /api/ui-state         -> persist UI form state to ui_state.json
  POST /api/bot/start         -> start paper/live engine in a background thread
  POST /api/bot/stop          -> stop the running engine
  GET  /api/bot/status        -> running state + recent log lines + account snapshot

Run:  uvicorn server:app --reload --port 8000
Then open http://localhost:8000
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.settings import load_config, risk_from_config
from main import STRATEGY_REGISTRY, load_strategy
from risk.manager import RiskManager, RiskConfig
from core.models import AccountState

app = FastAPI(title="Futures Bot")

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "web"
CONFIG_FILE   = BASE_DIR / "config.yaml"
UI_STATE_FILE = BASE_DIR / "ui_state.json"

# ---- in-memory app state -------------------------------------------------
STATE = {
    "risk": risk_from_config(load_config(str(CONFIG_FILE))),
    "bot_thread": None,
    "bot_stop": threading.Event(),
    "bot_running": False,
    "bot_mode": None,
    "log": deque(maxlen=200),
    "account": {},
}

DEFAULT_PARAMS = {
    "ema_cross": {
        "ema_fast": 9, "ema_slow": 21, "rsi_period": 14,
        "rsi_overbought": 70, "rsi_oversold": 30,
        "atr_period": 14, "atr_mult": 2.0, "risk_reward": 2.0,
    },
    "rsi_mean_reversion": {
        "rsi_period": 14, "oversold": 30, "overbought": 70, "rsi_mid": 50,
        "atr_period": 14, "atr_mult": 1.5, "risk_reward": 2.0,
        "trend_filter": False, "sma_period": 200,
    },
    "bb_squeeze": {
        "bb_period": 20, "bb_std": 2.0, "squeeze_window": 20,
        "atr_period": 14, "atr_mult": 2.0, "risk_reward": 2.0,
        "macd_filter": True,
    },
    "macd_signal": {
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "atr_period": 14, "atr_mult": 2.0, "risk_reward": 2.0,
        "zero_line_filter": False,
    },
    "supertrend": {
        "st_period": 10, "st_multiplier": 3.0,
        "atr_period": 14, "atr_mult": 1.0, "risk_reward": 2.0,
    },
    "donchian_breakout": {
        "entry_period": 20, "exit_period": 10,
        "atr_period": 14, "atr_mult": 2.0, "risk_reward": 2.0,
    },
    "vwap_reversion": {
        "dev_threshold": 1.5, "rsi_period": 14,
        "rsi_oversold": 35, "rsi_overbought": 65,
        "atr_period": 14, "atr_mult": 1.5, "risk_reward": 1.5,
    },
    "vrvp_poc": {
        "vp_period": 200, "num_bins": 200,
        "mode": "reversion", "vwap_filter": True,
        "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
        "atr_period": 14, "atr_mult": 2.0, "risk_reward": 2.0,
    },
    "scalper": {
        "ema_fast": 8, "ema_slow": 21,
        "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
        "atr_period": 14, "atr_mult": 1.5, "risk_reward": 1.5,
    },
}

DEFAULT_UI_STATE: dict[str, Any] = {
    "bt_strategy": "ema_cross",
    "bt_pair": "BTCUSDT",
    "bt_interval": "1h",
    "bt_limit": 1000,
    "bt_leverage": 3,
    "bt_equity": 1000,
    "bt_params": {},
    "lv_mode": "paper",
    "lv_strategy": "ema_cross",
    "lv_pair": "BTCUSDT",
    "lv_interval": "15m",
    "lv_leverage": 3,
    "lv_params": {},
    "risk_per_trade": 0.01,
    "max_leverage": 5,
    "max_positions": 3,
    "daily_loss_limit": 0.05,
    "max_drawdown": 0.20,
}


def log(msg: str) -> None:
    STATE["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")


def _write_config_yaml(risk: RiskConfig) -> None:
    """Persist the risk section to config.yaml, preserving other keys."""
    cfg: dict = {}
    if CONFIG_FILE.exists():
        cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    cfg["risk"] = {
        "risk_per_trade":  risk.risk_per_trade,
        "max_leverage":    risk.max_leverage,
        "max_positions":   risk.max_positions,
        "daily_loss_limit": risk.daily_loss_limit,
        "max_drawdown":    risk.max_drawdown,
        "min_notional":    risk.min_notional,
    }
    CONFIG_FILE.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))


def _load_ui_state() -> dict:
    if UI_STATE_FILE.exists():
        try:
            saved = json.loads(UI_STATE_FILE.read_text())
            return {**DEFAULT_UI_STATE, **saved}
        except Exception:
            pass
    return dict(DEFAULT_UI_STATE)


def _save_ui_state(data: dict) -> None:
    current = _load_ui_state()
    current.update(data)
    UI_STATE_FILE.write_text(json.dumps(current, indent=2))


# ---- request models ------------------------------------------------------
class BacktestReq(BaseModel):
    strategy: str = "ema_cross"
    pair: str = "BTCUSDT"
    interval: str = "1h"
    limit: int = 1000
    leverage: int = 3
    start_equity: float = 1000
    params: dict = {}


class RiskReq(BaseModel):
    risk_per_trade: float
    max_leverage: int
    max_positions: int
    daily_loss_limit: float
    max_drawdown: float
    min_notional: float = 5.0


class BotReq(BaseModel):
    mode: str = "paper"          # paper | live
    strategy: str = "ema_cross"
    pair: str = "BTCUSDT"
    interval: str = "15m"
    leverage: int = 3
    params: dict = {}


class UiStateReq(BaseModel):
    state: dict


# ---- endpoints -----------------------------------------------------------
@app.get("/api/strategies")
def strategies():
    return [{"name": n, "params": DEFAULT_PARAMS.get(n, {})} for n in STRATEGY_REGISTRY]


@app.get("/api/config")
def get_config():
    r: RiskConfig = STATE["risk"]
    return r.__dict__


@app.post("/api/config")
def set_config(req: RiskReq):
    rc = RiskConfig(**req.model_dump())
    STATE["risk"] = rc
    _write_config_yaml(rc)
    log(f"Risk config saved: {req.model_dump()}")
    return rc.__dict__


@app.get("/api/ui-state")
def get_ui_state():
    return _load_ui_state()


@app.post("/api/ui-state")
def set_ui_state(req: UiStateReq):
    _save_ui_state(req.state)
    return {"saved": True}


@app.post("/api/backtest")
def run_backtest(req: BacktestReq):
    from core.exchange import BinanceFutures
    from backtest.engine import Backtester

    try:
        # Use empty keys for public klines endpoint - doesn't need auth
        ex = BinanceFutures("", "", testnet=False)
        df = ex.get_klines(req.pair, req.interval, limit=min(req.limit, 1500))
    except Exception as e:
        return {"error": f"Could not fetch klines: {e}. Make sure pair '{req.pair}' is valid."}

    params = {**DEFAULT_PARAMS.get(req.strategy, {}), **req.params}
    # Normalize mode param (UI sends 0/1, strategy expects reversion/breakout)
    if "mode" in params and isinstance(params["mode"], (int, float)):
        params["mode"] = "reversion" if params["mode"] == 0 else "breakout"
    strat = load_strategy(req.strategy, params)
    risk = RiskManager(STATE["risk"])
    bt = Backtester(strat, risk, start_equity=req.start_equity, leverage=req.leverage)
    result = bt.run(df, req.pair)

    eq = result.equity_curve
    step = max(1, len(eq) // 300)
    return {
        "summary": result.summary(),
        "equity_curve": eq[::step],
        "trades": [
            {"side": t.side, "entry": round(t.entry, 2), "exit": round(t.exit, 2),
             "pnl": round(t.pnl, 2), "reason": t.reason}
            for t in result.trades
        ],
    }


def _bot_loop(req: BotReq):
    from core.exchange import BinanceFutures
    from core.engine import TradingEngine

    cfg = load_config(str(CONFIG_FILE))
    if not cfg["api_key"]:
        log("ERROR: no API keys set. Bot cannot start.")
        STATE["bot_running"] = False
        return

    params = {**DEFAULT_PARAMS.get(req.strategy, {}), **req.params}
    # Normalize mode param (UI sends 0/1, strategy expects reversion/breakout)
    if "mode" in params and isinstance(params["mode"], (int, float)):
        params["mode"] = "reversion" if params["mode"] == 0 else "breakout"
    strat = load_strategy(req.strategy, params)
    risk = RiskManager(STATE["risk"])
    risk.reset_day(AccountState())  # Reset killswitch on fresh start
    ex = BinanceFutures(cfg["api_key"], cfg["api_secret"], testnet=(req.mode == "paper"))
    engine = TradingEngine(ex, strat, risk, req.pair, req.interval, req.leverage, logger=log)

    interval_s = {"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}.get(req.interval,900)
    log(f"Bot started ({req.mode}) {req.pair} {req.interval} strat={req.strategy}")

    while not STATE["bot_stop"].is_set():
        try:
            engine.step()
            # Update UI after each step
            acct = engine._sync_account()
            STATE["account"] = {
                "balance": round(acct.balance, 2),
                "equity": round(acct.equity, 2),
                "positions": len(acct.open_positions),
            }
        except Exception as e:
            log(f"ERROR: {e}")
        STATE["bot_stop"].wait(timeout=interval_s - (time.time() % interval_s) + 2)

    STATE["bot_running"] = False
    log("Bot stopped.")


@app.post("/api/bot/start")
def bot_start(req: BotReq):
    if STATE["bot_running"]:
        return {"error": "Bot already running"}
    STATE["bot_stop"].clear()
    STATE["bot_running"] = True
    STATE["bot_mode"] = req.mode
    t = threading.Thread(target=_bot_loop, args=(req,), daemon=True)
    STATE["bot_thread"] = t
    t.start()
    return {"running": True, "mode": req.mode}


@app.post("/api/bot/stop")
def bot_stop():
    STATE["bot_stop"].set()
    return {"running": False}


@app.get("/api/bot/status")
def bot_status():
    return {
        "running": STATE["bot_running"],
        "mode": STATE["bot_mode"],
        "account": STATE["account"],
        "log": list(STATE["log"])[-50:],
    }


# ---- static UI -----------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/web", StaticFiles(directory=STATIC_DIR), name="web")
