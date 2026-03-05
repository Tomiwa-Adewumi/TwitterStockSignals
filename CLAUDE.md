# Twitter Stock Digest — CLAUDE.md

## Overview

Automated pipeline that runs daily via GitHub Actions:

1. **Fetch tweets** — X API v2 fetches today's tweets from configured Twitter/X users
2. **Extract tickers** — Claude identifies stock ticker symbols in the tweets
3. **Research** — yfinance pulls fundamentals; DuckDuckGo fetches news headlines per ticker
4. **Load history** — SQLite (`signals.db`) provides the last 30 days of signals as context
5. **Analyze** — Claude produces BUY/SELL/HOLD/INVESTIGATE signals with reasoning
6. **Persist** — New signals saved to `signals.db`, which is committed back to the repo
7. **Email** — HTML digest sent via Gmail SMTP with signal table + raw tweets

**Cost:** ~$0.01–0.05/day (Claude API only; yfinance and DuckDuckGo are free).

---

## Project Structure

```
main.py          # Entry point / pipeline orchestration
scraper.py       # X API v2 Bearer Token tweet fetcher
researcher.py    # yfinance + DuckDuckGo per-ticker research
analyzer.py      # Claude: ticker extraction + signal analysis
database.py      # SQLite read/write for signal history
emailer.py       # HTML email builder + SMTP sender
config.yaml      # Users, email settings, AI model config
signals.db       # SQLite history (tracked in git, grows over time)
.env.example     # Template for local secrets
.env             # Local secrets (gitignored — never commit this)
requirements.txt
.github/workflows/digest.yml
```

---

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
```

### Required `.env` values

| Variable | Description |
|---|---|
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your main password) |
| `TWITTER_BEARER_TOKEN` | X API v2 Bearer Token (from developer.x.com) |
| `ANTHROPIC_API_KEY` | From https://console.anthropic.com |

**Get your Bearer Token:** Go to [developer.x.com](https://developer.x.com) → Your App → Keys & Tokens → Bearer Token.

**Rate limits:** Free tier allows ~1,500 tweets/month; paid tiers allow more.

---

## Running Locally

```bash
# Dry run — prints HTML to stdout, no email sent
python main.py --dry-run

# Full run — fetches tweets, analyzes, emails
python main.py

# Weekly label in email subject
python main.py --weekly

# Custom config file
python main.py --config path/to/config.yaml
```

---

## GitHub Actions Secrets

Set these in your repo → Settings → Secrets and variables → Actions:

- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `TWITTER_BEARER_TOKEN`
- `ANTHROPIC_API_KEY`

The workflow runs daily at 07:00 UTC and can also be triggered manually via **workflow_dispatch**.

---

## signals.db

`signals.db` is a SQLite database tracked in git. After each run, the Actions workflow commits the updated file back to the repo with `[skip ci]` in the commit message (to avoid infinite loops).

This allows Claude to see signal history across days and spot trends (e.g., "NVDA was signaled BUY 5 of the last 7 days").

**To inspect manually:**
```bash
sqlite3 signals.db "SELECT * FROM signals ORDER BY id DESC LIMIT 10;"
sqlite3 signals.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5;"
```

---

## Adding / Removing Tracked Users

Edit `config.yaml`:

```yaml
users:
  - paulg
  - naval
  - karpathy
  - elonmusk   # add
```

Twitter handles only (no `@`).

