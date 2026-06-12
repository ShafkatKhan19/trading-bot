# Trading Bot — AI Infrastructure Swing Trader

Swing trading bot for US AI infrastructure stocks with a news sentiment
sub-agent, 25% kill switch, and a paper-tested rule constitution
that locks before any live trading begins.

---

## Quick start

```bash
# 1. Navigate to project folder on your N: drive
cd N:\trading-bot

# 2. Activate virtual environment
venv\Scripts\activate

# 3. Install packages
pip install -r requirements.txt

# 4. Copy .env.example to .env and fill in your keys
copy .env.example .env

# 5. Start paper trading (runs until 500 trades complete)
python paper_runner.py

# 6. After 500 trades — build the constitution
python constitution_builder.py

# 7. Switch .env to live mode and run
python main.py
```

---

## File map

| File | Purpose |
|---|---|
| `config.py` | Watchlist, risk settings, all tunable parameters |
| `alpaca_client.py` | Alpaca paper + live API wrapper |
| `signals.py` | RSI, MA crossover, MACD, volume calculations |
| `news_agent.py` | News headline sentiment scoring |
| `kill_switch.py` | 25% daily loss monitor — closes all positions |
| `trade_logger.py` | SQLite trade database |
| `strategy.py` | Swing trade entry + exit logic |
| `paper_runner.py` | 500-run paper test engine |
| `constitution_builder.py` | Extracts winning rules from paper trades |
| `constitution_validator.py` | SHA-256 hash check — guards live trading |
| `main.py` | Live trading entry point |
| `.env` | Your API keys (never commit this) |

---

## Watchlist — AI infrastructure supply chain

| Ticker | Company | Theme |
|---|---|---|
| NVDA | Nvidia | AI core |
| AMD | AMD | AI core |
| MSFT | Microsoft | AI core |
| GOOGL | Alphabet | AI core |
| AVGO | Broadcom | AI infra |
| VRT | Vertiv | Cooling |
| ETN | Eaton | Power |
| GEV | GE Vernova | Power |
| EQIX | Equinix | Data centers |
| SMCI | Super Micro | AI servers |
| UNP | Union Pacific | Transport |
| FDX | FedEx | Transport |

---

## Kill switch

Set in `.env`:
```
KILL_SWITCH_PCT=25
```
If the portfolio drops 25% from the session start value, the bot:
1. Cancels all open orders
2. Closes all positions at market
3. Locks itself until next market open
4. Logs the event to `logs/kill_switch_events.json`

---

## Constitution system

After 500 paper trades, run:
```bash
python constitution_builder.py
```

This analyses every trade and writes `constitution.json` — a locked
rule set with a SHA-256 hash. In live mode, the bot verifies the hash
before every trade. If the file is edited, the hash fails and the bot
refuses to run.

To update the constitution: complete another 500-run paper cycle.

---

## Paper → live switch

Change one line in `.env`:
```
# Paper:
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Live (after constitution is verified):
ALPACA_BASE_URL=https://api.alpaca.markets
TRADING_MODE=live
```

Same code. Same API. Same strategy. No rewrite.
