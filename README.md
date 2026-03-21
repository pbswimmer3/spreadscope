# SpreadScope

A funding rate carry trade research tool that monitors perpetual futures funding rates, detects profitable carry opportunities, and stores bot-readable trading signals.

**Research and signal generation only — does not execute trades.**

---

## What Is Funding Rate Carry?

### The Short Version

Perpetual futures contracts (perps) have no expiration date. To keep their price in line with the underlying spot price, exchanges charge a **funding rate** — a periodic payment between traders holding long and short positions.

When the funding rate is **positive**, traders who are long pay traders who are short. You can collect this payment by:

1. **Buying the asset on spot** (e.g., buy 1 BTC on Coinbase for $70,000)
2. **Shorting the same asset on perps** (e.g., short 1 BTC on Hyperliquid)

Your net market exposure is zero (the spot long and perp short cancel out), but you collect the funding payment every 8 hours. This is called a **cash-and-carry trade** or **funding rate arbitrage**.

### The Detailed Version

#### How Funding Rates Work

Perpetual futures on crypto exchanges (Hyperliquid, dYdX, Binance, etc.) charge funding every 8 hours. The rate is determined by the difference between the perp price and the spot price:

- **Perp price > spot price** (bullish sentiment) → Positive funding rate → Longs pay shorts
- **Perp price < spot price** (bearish sentiment) → Negative funding rate → Shorts pay longs

A typical funding rate might be **0.01% per 8 hours**. That sounds tiny, but it compounds:

```
0.01% per 8h × 3 periods/day × 365 days = 10.95% APY
```

During bullish market conditions, funding rates can spike much higher:

```
0.03% per 8h = 32.85% APY
0.05% per 8h = 54.75% APY
```

#### The Carry Trade Mechanics

Here's a concrete example with a $5,000 portfolio:

1. **Entry:**
   - You see BTC funding rate at 0.02%/8h (21.9% APY) on Hyperliquid
   - You buy $2,000 of BTC on Coinbase (spot)
   - You short $2,000 of BTC on Hyperliquid (perp)

2. **Collecting Yield:**
   - Every 8 hours, you receive 0.02% of your short position: $2,000 × 0.0002 = $0.40
   - That's $1.20/day or ~$438/year on a $2,000 position

3. **Market Neutrality:**
   - If BTC goes up 10%, your spot position gains $200 and your short loses $200 → net zero
   - If BTC goes down 10%, your spot position loses $200 and your short gains $200 → net zero
   - Your profit comes purely from funding payments, not price movement

4. **Exit:**
   - When funding rates drop below your threshold, close both positions
   - Total P&L = funding collected - entry/exit trading fees

#### Why This Works for Retail

Unlike high-frequency spread arbitrage (which requires microsecond execution and is dominated by professional firms), funding rate carry:

- Operates on **8-hour cycles** — no speed advantage needed
- Requires only **basic exchange access** (spot buy + perp short)
- Works at **any capital level** (though fees eat more at smaller sizes)
- Is inherently **market-neutral** — you don't need to predict price direction

#### The Risks

- **Funding rate reversal**: If rates go negative, you start paying instead of collecting
- **Liquidation risk**: If your perp margin is too thin and the price moves sharply, your short could get liquidated before your spot hedge offsets it
- **Exchange risk**: Counterparty risk on the perp exchange
- **Fee drag**: Entry/exit fees on both legs eat into returns. At $5K capital with 0.06% taker fees, you need ~192 hours of positive funding just to break even on fees

### What SpreadScope Does

SpreadScope automates the **detection** side of this strategy:

1. **Collects** funding rates from perp exchanges every 15-30 seconds
2. **Evaluates** whether rates meet entry criteria (APY threshold, consecutive confirmations, acceptable spread)
3. **Generates signals** with position sizing, expected returns, and breakeven analysis
4. **Stores signals** in a database with a JSON API that a trading bot can read

It does **not** execute trades — that's left for a separate bot to handle.

---

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│                                                           │
│  Ingestion Workers (Python/asyncio)                       │
│    ├── coinbase_spot    → spot prices (BTC, ETH)          │
│    └── hyperliquid_perps → perp prices + funding rates    │
│                ↓                                          │
│  PostgreSQL + TimescaleDB                                 │
│    ├── price_observations  (hypertable, 90d retention)    │
│    ├── funding_rate_snapshots (hypertable, 1yr retention) │
│    ├── spreads             (hypertable, 180d retention)   │
│    ├── carry_signals       (bot-readable signals)         │
│    └── continuous aggregates (hourly rollups)             │
│                ↓                                          │
│  Carry Calculator (30s loop)                              │
│    ├── Reads latest prices + funding rates from DB        │
│    ├── Evaluates entry/exit conditions                    │
│    ├── Computes position sizing + expected returns        │
│    └── Writes CarrySignal records to DB                   │
│                ↓                                          │
│  Flask Dashboard (port 8050)                              │
│    ├── /           → live funding rates + signals         │
│    ├── /analytics  → historical patterns + charts         │
│    └── /api/*      → JSON API for bots                   │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### Three Processes

SpreadScope runs as three independent processes:

| Process | Script | Purpose |
|---------|--------|---------|
| **Ingestion** | `run_ingestion.py` | Fetches prices and funding rates from exchanges |
| **Calculator** | `run_calculator.py` | Analyzes data and generates carry signals |
| **Dashboard** | `run_dashboard.py` | Web UI and JSON API |

They communicate through the shared PostgreSQL database — no message queues or IPC needed.

---

## Quick Start

### One-Command Deploy

```bash
sudo bash deploy.sh
```

This handles everything: Python venv, pip install, PostgreSQL database creation, TimescaleDB setup, schema loading, seed data, and config generation.

### Start the Services

```bash
cd /path/to/spreadscope

# Start all three (background)
.venv/bin/python run_ingestion.py &
.venv/bin/python run_calculator.py &
.venv/bin/python run_dashboard.py &

# Or use the generated config explicitly
.venv/bin/python run_ingestion.py -c config/config.yaml &
.venv/bin/python run_calculator.py -c config/config.yaml &
.venv/bin/python run_dashboard.py -c config/config.yaml &
```

### Access the Dashboard

Open `http://localhost:8050` in your browser.

---

## Configuration Reference

All settings live in `config/config.yaml`. Here's every parameter and what it does:

### Database

```yaml
database:
  host: localhost
  port: 5432
  name: spreadscope_db
  user: spreadscope
  password: your_password_here
```

### Venues

Controls which exchanges to poll. Only `coinbase_spot` and `hyperliquid` are needed for the carry strategy.

```yaml
venues:
  coinbase_spot:
    base_url: https://api.coinbase.com
    polling_interval: 30    # seconds between API calls
    enabled: true           # toggle this venue on/off

  hyperliquid:
    base_url: https://api.hyperliquid.xyz
    polling_interval: 15
    enabled: true

  # These are optional / geo-restricted:
  dydx:
    enabled: false          # 403 in some regions
  synthetix:
    enabled: false          # 403 in some regions
```

### Assets

Which assets to track:

```yaml
assets:
  - BTC
  - ETH
```

### Portfolio (Position Sizing)

This is where you set your capital. **Change `capital_usd` to match your actual portfolio.**

```yaml
portfolio:
  capital_usd: 5000         # Your total capital — all sizing derives from this
  max_position_pct: 50       # Max 50% of capital in a single carry position
  min_position_usd: 100      # Don't bother with positions smaller than $100
  fee_per_trade_pct: 0.06    # Taker fee per leg (Hyperliquid is 0.035%, using 0.06% conservative)
```

**How position sizing works:**

The calculator uses `min(capital * max_position_pct/100, capital * 0.4)` as the suggested position size. With default settings:

| Capital | Position Size | Daily Return (at 0.02%/8h) | Annual Return | Breakeven |
|---------|--------------|---------------------------|---------------|-----------|
| $1,000 | $400 | $0.12 | $44 | 192h |
| $5,000 | $2,000 | $0.60 | $219 | 192h |
| $10,000 | $4,000 | $1.20 | $438 | 192h |
| $25,000 | $10,000 | $3.00 | $1,095 | 192h |
| $50,000 | $20,000 | $6.00 | $2,190 | 192h |

### Carry (Signal Thresholds)

These control when the calculator generates ENTRY and EXIT signals:

```yaml
carry:
  min_annualized_rate_pct: 10.0   # Only signal when APY > 10%
  min_funding_rate_pct: 0.01      # Raw 8h rate must be > 0.01% (filters noise)
  confirmation_periods: 3         # Must see 3+ consecutive positive readings before signaling
  max_entry_spread_pct: 0.15      # Don't enter if spot-perp spread > 0.15% (too expensive)
  exit_funding_rate_pct: 0.005    # Signal EXIT when 8h rate drops below 0.005%
  spot_venues:
    - coinbase_spot               # Where to check spot prices
  perp_venues:
    - hyperliquid_perps           # Where to check funding rates
```

**Tuning guide:**

| Parameter | Lower Value | Higher Value |
|-----------|-------------|--------------|
| `min_annualized_rate_pct` | More signals, lower quality | Fewer signals, higher quality |
| `confirmation_periods` | Faster entry, more false positives | Slower entry, more confirmed |
| `max_entry_spread_pct` | Tighter entry, fewer trades | Looser entry, worse fill prices |
| `exit_funding_rate_pct` | Hold longer, risk rate reversal | Exit earlier, lock in profits |

### Thresholds (Spread Monitoring)

Legacy spread monitoring — still runs alongside the carry calculator:

```yaml
thresholds:
  default_pct: 0.05              # Flag spreads above 0.05%
  staleness_max_seconds: 120     # Ignore prices older than 2 minutes
```

---

## API Endpoints

All endpoints return JSON. These are designed for bot consumption.

### Funding Rates

```
GET /api/funding/current
```
Returns the latest funding rate for each asset/venue combo. Response:
```json
{
  "status": "ok",
  "rates": [
    {
      "asset": "BTC",
      "venue": "hyperliquid_perps",
      "funding_rate": 0.0002,
      "annualized_rate": 21.9,
      "mark_price": 70650.0,
      "open_interest": 26800.0,
      "seconds_ago": "5.2"
    }
  ]
}
```

```
GET /api/funding/history?asset=BTC&venue=hyperliquid_perps&hours=72
```
Returns funding rate time series for charting.

### Carry Signals (Bot-Readable)

```
GET /api/signals?status=active
```
Returns all active carry signals. A trading bot should poll this endpoint. Response:
```json
{
  "status": "ok",
  "signals": [
    {
      "id": 1,
      "asset": "BTC",
      "spot_venue": "coinbase_spot",
      "perp_venue": "hyperliquid_perps",
      "signal_type": "entry",
      "status": "active",
      "funding_rate_8h": 0.0002,
      "annualized_rate": 21.9,
      "suggested_size_usd": 2000.0,
      "expected_daily_return_usd": 1.2,
      "expected_apy_pct": 21.9,
      "estimated_fees_usd": 2.4,
      "breakeven_hours": 48.0,
      "spot_price": 70650.0,
      "perp_price": 70680.0,
      "created_at": "2026-03-21T10:00:00+00:00"
    }
  ]
}
```

```
GET /api/signals?status=all&limit=50
```
Returns recent signals of all statuses (active, executed, expired, cancelled).

### Spreads

```
GET /api/spreads/current
GET /api/spreads/history?asset=BTC&pair=coinbase_spot:hyperliquid_perps&hours=24
```

### Analytics & Stats

```
GET /api/analytics
GET /api/signals/stats?days=7
GET /api/health
```

---

## Debugging

### Dry-Run Mode

Run any component without touching the database:

```bash
# Ingestion: prints what it would write
.venv/bin/python run_ingestion.py --dry-run

# Calculator: runs logic tests with synthetic data
.venv/bin/python run_calculator.py --test

# Dashboard: runs with placeholder data (no DB needed)
.venv/bin/python run_dashboard.py --no-db
```

### Test API Connections

```bash
.venv/bin/python tests/test_apis_dryrun.py
```

This hits every exchange API and reports which ones are accessible from your network.

### Run Unit Tests

```bash
# All tests (no external dependencies needed)
.venv/bin/python tests/test_carry_logic.py      # Funding rate math + models
.venv/bin/python tests/test_spread_logic.py      # Spread calculation
.venv/bin/python tests/test_dashboard_nodeps.py  # Dashboard route structure

# Integration test (requires asyncpg + running DB)
.venv/bin/python -m pytest tests/test_spread_engine.py
```

### Check What's in the Database

```bash
# Connect directly
psql -h localhost -U spreadscope -d spreadscope_db

# Useful queries:
SELECT count(*) FROM price_observations;
SELECT count(*) FROM funding_rate_snapshots;
SELECT count(*) FROM carry_signals;

-- Latest funding rates
SELECT asset, venue, funding_rate * 100 as rate_pct,
       annualized_rate as apy, time
FROM funding_rate_snapshots
ORDER BY time DESC LIMIT 10;

-- Active signals
SELECT * FROM carry_signals WHERE status = 'active';
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `password authentication failed` | Stale config at `/opt/spreadscope/config/config.yaml` being loaded first | Ensure `./config/config.yaml` exists (it takes priority) or pass `--config` explicitly |
| Hyperliquid shows no data | Metadata parsing bug (fixed in current version) | Pull latest code |
| Dashboard says "Connecting..." | Analytics page doesn't auto-refresh | Refresh the page; the main dashboard auto-refreshes every 15s |
| dYdX / Synthetix returning 403 | Geo-restricted APIs | Set `enabled: false` in config (default) |
| `Address already in use` on port 8050 | Old process or system service on that port | Use `--port 8051` or kill the old process |
| No carry signals generated | Funding rates are below threshold | Normal — signals only appear when APY > `min_annualized_rate_pct` |

### Log Verbosity

The logging level is set in config:

```yaml
logging:
  level: INFO    # Options: DEBUG, INFO, WARNING, ERROR
```

Set to `DEBUG` to see every API call, every price observation, and every funding rate evaluation.

---

## File Structure

```
spreadscope/
├── deploy.sh                      # One-command setup script
├── schema.sql                     # Full database schema (TimescaleDB)
├── requirements.txt               # Python dependencies
├── config/
│   ├── config.example.yaml        # Template config
│   └── config.yaml                # Your config (gitignored)
├── src/
│   ├── models.py                  # Dataclasses: PriceObservation, FundingRateSnapshot, CarrySignal, etc.
│   ├── db.py                      # Async database layer (asyncpg)
│   ├── utils.py                   # Config loading, rate limiting, helpers
│   ├── ingestion/
│   │   ├── base_worker.py         # Base class for all ingestion workers
│   │   ├── coinbase_spot_worker.py
│   │   ├── hyperliquid_worker.py  # Prices + funding rates
│   │   ├── dydx_worker.py
│   │   ├── synthetix_worker.py
│   │   ├── polygon_worker.py
│   │   └── coinbase_perps_worker.py
│   ├── calculator/
│   │   ├── carry_calculator.py    # Core carry logic: evaluate, size, signal
│   │   ├── spread_engine.py       # Legacy spread calculator
│   │   └── opportunity_tracker.py # Legacy opportunity tracker
│   └── dashboard/
│       ├── app.py                 # Flask app factory
│       ├── routes.py              # All HTTP routes + JSON API
│       ├── db_sync.py             # Sync psycopg2 queries (avoids async/Flask conflicts)
│       ├── templates/             # Jinja2 HTML templates
│       └── static/                # CSS + JS (Chart.js, Lightweight Charts)
├── services/                      # systemd unit files for production
├── setup/                         # Host setup scripts
├── tests/
│   ├── test_carry_logic.py        # Funding rate math tests
│   ├── test_spread_logic.py       # Spread calculation tests
│   ├── test_dashboard_nodeps.py   # Dashboard structure tests
│   ├── test_spread_engine.py      # Integration test (needs DB)
│   └── test_apis_dryrun.py        # Live API connectivity test
├── run_ingestion.py               # Entrypoint: start ingestion workers
├── run_calculator.py              # Entrypoint: start carry calculator
└── run_dashboard.py               # Entrypoint: start web dashboard
```

---

## Tech Stack

- **Python 3.12** with asyncio for concurrent data ingestion
- **asyncpg** for async PostgreSQL (ingestion + calculator)
- **psycopg2** for sync PostgreSQL (Flask dashboard)
- **aiohttp** for HTTP API requests
- **Flask** for web dashboard and JSON API
- **Chart.js** + **TradingView Lightweight Charts** for visualization
- **PostgreSQL 16** + **TimescaleDB 2.x** for time-series storage with automatic retention and continuous aggregates
