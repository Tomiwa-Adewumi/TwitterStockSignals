# Twitter Stock Signals API

A FastAPI backend for asynchronous research processing: accept a job, persist its lifecycle, call external data/AI adapters, and expose results through a paginated API. The original scheduled digest remains available as a CLI.

**Engineering focus:** recoverable jobs, transactional persistence, input validation, adapter-boundary tests, and container delivery. The service supports one application instance; generated signals are not evidence of investment performance.

[Architecture](docs/architecture.md) · [CI](https://github.com/Tomiwa-Adewumi/TwitterStockSignals/actions/workflows/tests.yml)

## Try it without credentials

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python demo.py
```

This runs the real orchestration and SQLite persistence with synthetic adapters, prints the completed run and one `DEMO` signal, and measures local elapsed time. It makes no network or email calls. Timing excludes real provider latency and is not a production benchmark.

```json
{"kind": "synthetic-offline-demo", "signal_count": 1}
```

The full output also contains the stored run, signal, and measured elapsed time.

---

## How It Works

```text
Tweets (X API v2) → Ticker Extraction (Claude) → Research (yfinance + DuckDuckGo)
      → Signal History (SQLite) → Analysis (Claude) → HTML Email (Gmail SMTP)
```

1. **Fetch tweets** — X API v2 fetches today's tweets from your configured Twitter/X accounts
2. **Extract tickers** — Claude identifies stock ticker symbols mentioned in the tweets
3. **Research** — yfinance pulls fundamentals; DuckDuckGo fetches recent news per ticker
4. **Load history** — SQLite (`signals.db`) provides the last 30 days of signals as context
5. **Analyze** — Claude produces BUY/SELL/HOLD/INVESTIGATE signals with reasoning and confidence levels
6. **Persist** — New signals are saved to `signals.db`, which is stored in a persistent volume or workflow snapshot
7. **Email** — An HTML digest is sent via Gmail SMTP with a signal table + raw tweets

**Cost:** varies with provider plans, model, input volume, and retries; no measured production cost is claimed here.

---

## Features

- FastAPI service with generated OpenAPI, Swagger UI, and ReDoc
- Asynchronous analysis jobs with queued/running/completed/failed lifecycle
- Paginated signal and run-history endpoints
- Secure-by-default API-key protection for analysis triggers
- SQLite schema migration for existing installations
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
| `main.py` | Backward-compatible CLI entry point |
| `api.py` | FastAPI application and HTTP routes |
| `pipeline.py` | Reusable orchestration shared by API and CLI |
| `worker.py` | Recoverable SQLite-backed analysis worker |
| `schemas.py` | Validated API request and response models |
| `tests/` | Unit, API, database integration, and end-to-end tests |
| `.github/workflows/tests.yml` | Required lint and test quality gate |
| `docs/architecture.md` | Reliability, security, and scaling decisions |
| `scraper.py` | X API v2 Bearer Token tweet fetcher |
| `researcher.py` | yfinance + DuckDuckGo per-ticker research |
| `analyzer.py` | Claude: ticker extraction + signal analysis |
| `database.py` | SQLite read/write for signal history |
| `emailer.py` | HTML email builder + Gmail SMTP sender |
| `config.yaml` | Users, email settings, AI model config |
| `signals.db` | Runtime SQLite history (ignored by Git) |
| `.env.example` | Template for local secrets |
| `.github/workflows/digest.yml` | GitHub Actions workflow |

---

## Setup

### Prerequisites

- Python 3.11+
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) enabled
- An X Developer account with a Bearer Token ([developer.x.com](https://developer.x.com))
- An [Anthropic API key](https://console.anthropic.com)

### Required Secrets

These are set as GitHub Actions secrets (Settings → Secrets and variables → Actions) for automated runs, or in a local `.env` file for local runs.

| Variable | Description |
| --- | --- |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your main password) |
| `TWITTER_BEARER_TOKEN` | X API v2 Bearer Token (from [developer.x.com](https://developer.x.com)) |
| `ANTHROPIC_API_KEY` | From <https://console.anthropic.com> |

**Get your Bearer Token:** Go to [developer.x.com](https://developer.x.com) → Your App → Keys & Tokens → Bearer Token. Check the provider dashboard for your account’s current access and quota.

The HTTP service additionally requires an `API_KEY` of your choosing for
`POST /analysis`; the scheduled CLI workflow does not.

---

## Running on GitHub Actions (recommended)

1. Fork this repo
2. Add the four secrets listed above under **Settings → Secrets and variables → Actions**
3. The workflow runs automatically every day at **07:00 UTC**
4. You can also trigger it manually via **Actions → Daily Digest → Run workflow**

After each run, the workflow saves `signals.db` as a `digest-state` artifact and restores the newest snapshot on the next run. The initial migration reads the final tracked database from Git history. Source history is no longer updated by digest runs.

Artifacts expire after 90 days and are not permanent backups. An expired latest snapshot stops the workflow instead of silently starting over. Deleting all snapshots causes the migration seed to be used again; restore an external backup before running if that occurs. For durable operation, use the container's persistent volume, schedule the CLI on that host, and back up the database independently. Existing history remains recoverable in Git history.

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

Install the development requirements and run the complete backend quality
gate with `make install-dev && make check`. See
[Architecture](docs/architecture.md) for the component boundaries, job
lifecycle, recovery guarantees, and scaling path.

---

## API Service

Start the development server:

```bash
uvicorn api:app --reload
```

Swagger UI is available at <http://localhost:8000/docs>, ReDoc at
<http://localhost:8000/redoc>, and the generated schema at
<http://localhost:8000/openapi.json>.

`POST /analysis` returns `202 Accepted` with a persisted run ID. Follow its
`Location` response header until the run is completed or failed.

```bash
curl -i -X POST http://localhost:8000/analysis \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-with-a-long-random-value' \
  -d '{}'
curl 'http://localhost:8000/signals?limit=20&action=BUY'
curl http://localhost:8000/signals/NVDA
curl http://localhost:8000/runs
curl http://localhost:8000/health
```

Set `API_KEY` and send it in the `X-API-Key` header when triggering an
analysis. The write endpoint is disabled when no key is configured, unless
`ALLOW_UNAUTHENTICATED_ANALYSIS=true` is explicitly set for local
development. Read endpoints remain public. `CORS_ORIGINS`, `CONFIG_PATH`,
and `DATABASE_PATH` configure browser access and runtime file locations.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/analysis` | Queue a new analysis |
| `GET` | `/signals` | List and filter signals |
| `GET` | `/signals/{ticker}` | List a ticker's history |
| `GET` | `/runs` | List pipeline runs |
| `GET` | `/runs/{run_id}` | Inspect one run |
| `GET` | `/health` | Check service readiness |

Run with a persistent Docker volume:

```bash
docker build -t twitter-stock-signals .
docker volume create twitter-stock-data
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v twitter-stock-data:/data \
  twitter-stock-signals
```

Alternatively, copy `.env.example` to `.env` and run
`docker compose up --build`.

The service uses a SQLite-backed recoverable job queue for a single
application instance. Interrupted jobs are requeued on startup. Use a
distributed worker queue and managed database when scaling across instances.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite is split into unit tests, SQLite integration tests, FastAPI client
tests, and an end-to-end pipeline test. Network and delivery boundaries
(Anthropic, X, yfinance, DuckDuckGo, and SMTP) are mocked, so the suite does
not require credentials or make paid requests.

The `Backend quality gate` workflow runs lint, formatting, type checks, and
tests on Python 3.11 and 3.12 for every pull request, enforcing at least 80%
core-module coverage. It also builds and smoke-tests the production container.
The `master` branch requires all three jobs and an up-to-date branch, so
GitHub blocks merging when any quality check fails.

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

`signals.db` is an ignored runtime database. Download the `digest-state` artifact or use the persistent container volume, then inspect it locally:

```bash
# View recent signals
sqlite3 signals.db "SELECT * FROM signals ORDER BY id DESC LIMIT 10;"

# View recent runs
sqlite3 signals.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5;"
```

**Schema:**

- `signals`: generated ticker, action, confidence, reasoning, sources, and
  owning `run_id`
- `runs`: lifecycle status, period, timestamps, summary, tweet count,
  requested/sent email state, and bounded failure details

---

## Troubleshooting

### Bearer Token errors

If you see `401 Unauthorized` or `403 Forbidden` from the Twitter API:

1. Verify `TWITTER_BEARER_TOKEN` is set correctly in GitHub Actions secrets (or your local `.env`)
2. Regenerate the Bearer Token at [developer.x.com](https://developer.x.com) → Your App → Keys & Tokens
3. Update the secret and re-run

### Rate limits

If you see `429 Too Many Requests`, you have hit an account-specific X API rate limit. Options:
- Reduce the number of tracked users in `config.yaml`
- Upgrade to a paid X API tier
- Increase the delay between requests in `researcher.py`
