# Twitter Stock Digest

An automated pipeline that monitors curated X (Twitter) accounts daily, extracts stock ticker mentions, and emails a BUY/SELL/HOLD/INVESTIGATE signal digest — powered by Claude AI.

---

## How It Works

```text
Tweets (twscrape) → Ticker Extraction (Claude) → Research (yfinance + DuckDuckGo)
      → Signal History (SQLite) → Analysis (Claude) → HTML Email (Gmail SMTP)
```

1. **Fetch tweets** — twscrape pulls today's tweets from your configured Twitter/X accounts
2. **Extract tickers** — Claude identifies stock ticker symbols mentioned in the tweets
3. **Research** — yfinance pulls fundamentals; DuckDuckGo fetches recent news per ticker
4. **Load history** — SQLite (`signals.db`) provides the last 30 days of signals as context
5. **Analyze** — Claude produces BUY/SELL/HOLD/INVESTIGATE signals with reasoning and confidence levels
6. **Persist** — New signals are saved to `signals.db`, which is committed back to the repo
7. **Email** — An HTML digest is sent via Gmail SMTP with a signal table + raw tweets

**Cost:** ~$0.01–0.05/day (Claude API only; yfinance and DuckDuckGo are free).

---

## Features

- Tracks any list of Twitter/X accounts you configure
- AI-powered signal extraction with BUY / SELL / HOLD / INVESTIGATE actions
- Confidence levels (HIGH / MEDIUM / LOW) per signal
- 30-day rolling history so Claude can spot trends (e.g. "NVDA was BUY 5 of 7 days")
- Color-coded HTML email with collapsible raw tweet section
- Fully automated via GitHub Actions — no server needed

---

## Project Structure

| File | Description |
| --- | --- |
| `main.py` | Entry point and pipeline orchestration |
| `scraper.py` | twscrape async tweet fetcher |
| `researcher.py` | yfinance + DuckDuckGo per-ticker research |
| `analyzer.py` | Claude: ticker extraction + signal analysis |
| `database.py` | SQLite read/write for signal history |
| `emailer.py` | HTML email builder + Gmail SMTP sender |
| `config.yaml` | Users, email settings, AI model config |
| `signals.db` | SQLite history (tracked in git, grows over time) |
| `.env.example` | Template for local secrets |
| `.github/workflows/digest.yml` | GitHub Actions workflow |

---

## Setup

### Prerequisites

- Python 3.11+
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) enabled
- A Twitter/X account
- An [Anthropic API key](https://console.anthropic.com)

### Required Secrets

These are set as GitHub Actions secrets (Settings → Secrets and variables → Actions) for automated runs, or in a local `.env` file for local runs.

| Variable | Description |
| --- | --- |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your main password) |
| `TWS_USERNAME` | Twitter/X username |
| `TWS_PASSWORD` | Twitter/X password |
| `TWS_EMAIL` | Email associated with your Twitter account |
| `TWS_EMAIL_PASSWORD` | Password for that email |
| `TWS_COOKIES` | JSON string of browser cookies from twitter.com |
| `ANTHROPIC_API_KEY` | From <https://console.anthropic.com> |

### How to get Twitter cookies

1. Log in to [twitter.com](https://twitter.com) in your browser
2. Open DevTools → Application → Cookies → `https://twitter.com`
3. Copy the `auth_token` and `ct0` values
4. Format as: `TWS_COOKIES='{"auth_token": "...", "ct0": "..."}'`

---

## Running on GitHub Actions (recommended)

1. Fork this repo
2. Add all secrets listed above under **Settings → Secrets and variables → Actions**
3. The workflow runs automatically every day at **07:00 UTC**
4. You can also trigger it manually via **Actions → Daily Digest → Run workflow**

After each run, the workflow commits the updated `signals.db` back to the repo (with `[skip ci]` to avoid loops), so signal history accumulates over time.

---

## Running Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials

# Dry run — prints HTML to stdout, no email sent
python3 main.py --dry-run

# Full run — fetches tweets, analyzes, emails
python3 main.py

# Weekly label in email subject
python3 main.py --weekly

# Custom config file
python3 main.py --config path/to/config.yaml
```

---

## Configuration

Edit `config.yaml` to control which accounts are tracked and how the pipeline behaves:

```yaml
users:
  - paulg
  - naval
  - karpathy
  # Add or remove Twitter handles (no @ prefix)

email:
  to: you@example.com

ai:
  model: claude-opus-4-6
```

---

## Monitoring Signal History

`signals.db` is a SQLite database committed to the repo after each run. Inspect it locally:

```bash
# View recent signals
sqlite3 signals.db "SELECT * FROM signals ORDER BY id DESC LIMIT 10;"

# View recent runs
sqlite3 signals.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5;"
```

**Schema:**

- `signals`: `id`, `run_date`, `ticker`, `action`, `reasoning`, `confidence`, `source_tweet_urls`
- `runs`: `id`, `run_date`, `summary`, `tweet_count`

---

## Troubleshooting

### `NoAccountError` or authentication failures

Twitter cookies expire periodically. To fix:

1. Log in to twitter.com in your browser
2. Re-export `auth_token` and `ct0` from DevTools → Application → Cookies
3. Update the `TWS_COOKIES` secret in GitHub Actions (or your local `.env`)
4. Delete `accounts.db` locally if it exists — twscrape will re-seed on the next run

### Rate limits

If you see rate limit errors, reduce the number of tracked users in `config.yaml` or increase the delay between requests in `researcher.py`.
