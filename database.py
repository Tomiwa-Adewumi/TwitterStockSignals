"""SQLite persistence for pipeline runs and generated stock signals."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ActiveRunError(RuntimeError):
    """Raised when a new API run is requested while one is already active."""


TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    summary TEXT,
    tweet_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    period TEXT NOT NULL DEFAULT 'today',
    email_requested INTEGER NOT NULL DEFAULT 0,
    email_sent INTEGER NOT NULL DEFAULT 0,
    email_error TEXT,
    started_at TEXT,
    completed_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    reasoning TEXT,
    confidence TEXT,
    source_tweet_urls TEXT
);

"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_signals_ticker_id ON signals(ticker, id DESC);
CREATE INDEX IF NOT EXISTS idx_signals_run_date ON signals(run_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_run_id ON signals(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status_id ON runs(status, id DESC);
"""
_RUN_MIGRATIONS = {
    "status": "TEXT NOT NULL DEFAULT 'completed'",
    "period": "TEXT NOT NULL DEFAULT 'today'",
    "email_requested": "INTEGER NOT NULL DEFAULT 0",
    "email_sent": "INTEGER NOT NULL DEFAULT 0",
    "email_error": "TEXT",
    "started_at": "TEXT",
    "completed_at": "TEXT",
    "error": "TEXT",
}
_SIGNAL_MIGRATIONS = {
    "run_id": "INTEGER REFERENCES runs(id) ON DELETE SET NULL",
    "company_name": "TEXT NOT NULL DEFAULT ''",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    # Create tables first, then migrate old databases before creating new indexes.
    conn.executescript(TABLE_SCHEMA)
    _add_missing_columns(conn, "runs", _RUN_MIGRATIONS)
    _add_missing_columns(conn, "signals", _SIGNAL_MIGRATIONS)
    conn.executescript(INDEX_SCHEMA)
    conn.commit()
    return conn


def init_database(db_path: str) -> None:
    """Create or migrate the database schema."""
    with _connect(db_path):
        pass


def database_is_ready(db_path: str) -> bool:
    try:
        with _connect(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        logger.exception("Database health check failed")
        return False


def create_run(
    db_path: str,
    run_date: str,
    period: str = "today",
    *,
    ensure_idle: bool = False,
    email_requested: bool = False,
) -> int:
    """Create a queued run and return its identifier."""
    with _connect(db_path) as conn:
        if ensure_idle:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT id FROM runs WHERE status IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            if active:
                raise ActiveRunError(f"Run {active['id']} is already active")
        cursor = conn.execute(
            "INSERT INTO runs "
            "(run_date, status, period, tweet_count, email_requested) "
            "VALUES (?, 'queued', ?, 0, ?)",
            (run_date, period, int(email_requested)),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a run identifier")
        return int(cursor.lastrowid)


def claim_run(db_path: str, run_id: int) -> bool:
    """Atomically claim a queued run so it is executed only once."""
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE runs SET status = 'running', started_at = ?, error = NULL "
            "WHERE id = ? AND status = 'queued'",
            (_utc_now(), run_id),
        )
        return cursor.rowcount == 1


def mark_run_started(db_path: str, run_id: int) -> None:
    """Backward-compatible run transition helper."""
    if not claim_run(db_path, run_id):
        raise RuntimeError(f"Run {run_id} is not queued")


def recover_incomplete_runs(
    db_path: str, *, stale_after_minutes: int = 30
) -> list[dict]:
    """Requeue interrupted work and return every queued job.

    Fresh running jobs are left alone, which prevents another service process
    from stealing work that is still executing.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
    ).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE runs
               SET status = 'queued', started_at = NULL,
                   error = 'Recovered after worker interruption'
               WHERE status = 'running'
                 AND (started_at IS NULL OR started_at <= ?)""",
            (cutoff,),
        )
        rows = conn.execute(
            """SELECT * FROM runs
               WHERE status = 'queued'
               ORDER BY id ASC"""
        ).fetchall()
    return [dict(row) for row in rows]


def _signal_values(signal: Any) -> tuple:
    if hasattr(signal, "ticker"):
        ticker = signal.ticker
        company_name = getattr(signal, "company_name", "")
        action = signal.action
        reasoning = signal.reasoning
        confidence = signal.confidence
        source_tweets = signal.source_tweets
    else:
        ticker = signal["ticker"]
        company_name = signal.get("company_name", "")
        action = signal["action"]
        reasoning = signal.get("reasoning", "")
        confidence = signal.get("confidence", "")
        source_tweets = signal.get("source_tweets", [])
    return (
        str(ticker).upper(),
        company_name,
        str(action).upper(),
        reasoning,
        str(confidence).upper(),
        json.dumps(source_tweets),
    )


def persist_analysis(
    db_path: str,
    run_id: int,
    run_date: str,
    signals: list,
    summary: str,
    tweet_count: int,
) -> None:
    """Atomically persist analysis output while the run remains active."""
    with _connect(db_path) as conn:
        # Recovery may replay an interrupted run. Replace that run's output so
        # the persisted queue is at-least-once without duplicating signals.
        conn.execute("DELETE FROM signals WHERE run_id = ?", (run_id,))
        for signal in signals:
            ticker, company_name, action, reasoning, confidence, urls = _signal_values(
                signal
            )
            conn.execute(
                """INSERT INTO signals
                   (run_id, run_date, ticker, company_name, action, reasoning,
                    confidence, source_tweet_urls)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    run_date,
                    ticker,
                    company_name,
                    action,
                    reasoning,
                    confidence,
                    urls,
                ),
            )
        conn.execute(
            """UPDATE runs
               SET summary = ?, tweet_count = ?, error = NULL
               WHERE id = ?""",
            (summary, tweet_count, run_id),
        )
    logger.info("Saved %d signal(s) for run %d.", len(signals), run_id)


def finish_run(
    db_path: str,
    run_id: int,
    *,
    email_sent: bool = False,
    email_error: str | None = None,
) -> None:
    """Mark an analyzed run complete, independently of email delivery."""
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE runs
               SET status = 'completed', email_sent = ?, email_error = ?,
                   completed_at = ?
               WHERE id = ?""",
            (
                int(email_sent),
                email_error[:2000] if email_error else None,
                _utc_now(),
                run_id,
            ),
        )


def complete_run(
    db_path: str,
    run_id: int,
    run_date: str,
    signals: list,
    summary: str,
    tweet_count: int,
    email_sent: bool = False,
) -> None:
    """Backward-compatible helper that persists and completes a run."""
    persist_analysis(db_path, run_id, run_date, signals, summary, tweet_count)
    finish_run(db_path, run_id, email_sent=email_sent)


def fail_run(db_path: str, run_id: int, error: str) -> None:
    """Mark a run failed, storing a bounded error string."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET status = 'failed', error = ?, completed_at = ? "
            "WHERE id = ? AND status != 'completed'",
            (error[:2000], _utc_now(), run_id),
        )


def save_signals(
    db_path: str,
    run_date: str,
    signals: list,
    summary: str,
    tweet_count: int,
) -> None:
    """Backward-compatible helper for callers that do not manage run state."""
    run_id = create_run(db_path, run_date)
    mark_run_started(db_path, run_id)
    complete_run(db_path, run_id, run_date, signals, summary, tweet_count)


def _decode_signal(row: sqlite3.Row) -> dict:
    result = dict(row)
    try:
        result["source_tweet_urls"] = json.loads(result["source_tweet_urls"] or "[]")
    except (json.JSONDecodeError, TypeError):
        result["source_tweet_urls"] = []
    return result


def get_history(db_path: str, days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE run_date >= ? ORDER BY run_date DESC, id DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_signals(
    db_path: str,
    *,
    ticker: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    clauses: list[str] = []
    params: list[Any] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if action:
        clauses.append("action = ?")
        params.append(action.upper())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM signals{where}", params).fetchone()[
            0
        ]
        rows = conn.execute(
            f"SELECT * FROM signals{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_decode_signal(row) for row in rows], int(total)


def list_runs(
    db_path: str, *, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(row) for row in rows], int(total)


def get_run(db_path: str, run_id: int) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def summarize_history(history: list[dict]) -> dict[str, dict]:
    """Aggregate raw history rows into per-ticker summaries for prompt injection."""
    summaries: dict[str, dict] = {}
    for row in history:
        ticker = row["ticker"]
        if ticker not in summaries:
            summaries[ticker] = {
                "total": 0,
                "actions": {},
                "last_seen": row["run_date"],
            }
        summaries[ticker]["total"] += 1
        action = row["action"]
        actions = summaries[ticker]["actions"]
        actions[action] = actions.get(action, 0) + 1
        summaries[ticker]["last_seen"] = max(
            summaries[ticker]["last_seen"], row["run_date"]
        )
    return summaries
