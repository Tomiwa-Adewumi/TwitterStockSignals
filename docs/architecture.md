# Architecture

Twitter Stock Signals is a single-instance backend that preserves the original
scheduled analysis pipeline while exposing it through an HTTP API.

## System flow

```text
POST /analysis
      │
      ▼
SQLite run record ──► in-process worker queue
      │                        │
      │                        ▼
      │              X API → Claude ticker extraction
      │                        │
      │                        ▼
      │              yfinance + news research
      │                        │
      │                        ▼
      │              Claude signal analysis
      │                        │
      ▼                        ▼
GET /runs ◄──── persisted signals and run state
GET /signals                  │
                              ▼
                       optional SMTP digest
```

## Components

| Component | Responsibility |
| --- | --- |
| `api.py` | HTTP contracts, authentication, pagination, health checks |
| `worker.py` | Queue consumption and interrupted-job recovery |
| `pipeline.py` | Application orchestration independent of HTTP and CLI |
| `database.py` | Transactions, migrations, lifecycle state, query functions |
| `scraper.py` | X API adapter with bounded rate-limit retries |
| `researcher.py` | Best-effort market-data and news adapters |
| `analyzer.py` | Claude adapter and response validation |
| `emailer.py` | Escaped HTML rendering and bounded SMTP delivery |

## Run lifecycle

```text
queued ──claim──► running ──analysis saved──► running
   ▲                                          │
   │                                          ├── delivery succeeds ──► completed
restart recovery                              └── delivery fails ─────► completed
                                              │                         + email_error
                                              └── fatal analysis error ► failed
```

Creating a run and checking for an active job happen under a SQLite
`BEGIN IMMEDIATE` transaction. Claiming a job is a conditional update, so
duplicate queue entries cannot execute the same queued run concurrently.

The worker requeues interrupted jobs on application startup. Persisting an
analysis replaces existing signals for that run, making recovery replay-safe.
SMTP delivery is tracked independently: a delivery failure cannot erase a
successfully generated signal set.

## Reliability boundaries

- The persisted run table is the source of truth; the in-memory queue is only
  a wake-up mechanism.
- X failures for every configured account fail the run. Partial account
  failures are tolerated and logged.
- Claude transport, malformed JSON, truncation, and invalid signal enums fail
  the run instead of masquerading as an empty successful analysis.
- Market-data and news failures degrade per ticker because they are optional
  research inputs.
- SQLite supports this deployment as one application instance. Moving to
  multiple instances requires a managed database and distributed queue.
- SMTP cannot provide exactly-once delivery. A hard crash immediately after
  SMTP accepts a message may result in a duplicate when the run is recovered.

## Security

- `POST /analysis` is disabled unless `API_KEY` is configured. An unsecured
  mode must be enabled explicitly for local development.
- API keys are compared using a constant-time comparison.
- Request bodies and path/query inputs are validated by Pydantic/FastAPI.
- AI and tweet content is escaped before HTML rendering; non-HTTP source URLs
  are rejected.
- The container runs as an unprivileged user and writes only to its persistent
  `/data` volume.

## Testing and delivery

The suite separates unit, database integration, FastAPI client, worker, and
end-to-end pipeline tests. External systems are mocked at adapter boundaries.
GitHub Actions runs formatting, linting, mypy, and coverage-gated tests on
Python 3.11 and 3.12, then builds and smoke-tests the container. Both matrix
jobs and the container job are required by branch protection.
