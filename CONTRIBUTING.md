# Contributing

Bug reports and pull requests are welcome! For major changes, please open an issue first.

## Development Setup

```bash
git clone <repo-url>
cd futures-bot
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
# Add your API keys to .env
```

## Running Tests

```bash
# Run backtest to verify strategy
python main.py backtest --strategy ema_cross --pair BTCUSDT --interval 1h --days 30
```

## Code Style

- Python type hints required for new functions
- Use `pydantic` models for API request/response validation
- No hardcoded secrets — use environment variables

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Run backtests to verify no regressions
4. Update documentation if needed
5. Submit PR with clear description of changes
