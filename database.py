"""
database.py — SQLite persistence for signal history (committed to repo).
"""

import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    reasoning TEXT,
    confidence TEXT,
    source_tweet_urls TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    summary TEXT,
    tweet_count INTEGER
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_history(db_path: str, days: int = 30) -> list[dict]:
    """
    Return signals from the last N days, newest first.

    Each dict has: run_date, ticker, action, reasoning, confidence, source_tweet_urls.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM signals WHERE run_date >= ? ORDER BY run_date DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_signals(
    db_path: str,
    run_date: str,
    signals: list,
    summary: str,
    tweet_count: int,
) -> None:
    """
    Persist signals and a run record to SQLite.

    `signals` is a list of StockSignal dataclass instances (or dicts with the same keys).
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (run_date, summary, tweet_count) VALUES (?, ?, ?)",
            (run_date, summary, tweet_count),
        )
        for sig in signals:
            # Support both dataclass and dict
            if hasattr(sig, "__dict__"):
                ticker = sig.ticker
                action = sig.action
                reasoning = sig.reasoning
                confidence = sig.confidence
                source_tweets = sig.source_tweets
            else:
                ticker = sig["ticker"]
                action = sig["action"]
                reasoning = sig.get("reasoning", "")
                confidence = sig.get("confidence", "")
                source_tweets = sig.get("source_tweets", [])

            conn.execute(
                """INSERT INTO signals
                   (run_date, ticker, action, reasoning, confidence, source_tweet_urls)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_date,
                    ticker,
                    action,
                    reasoning,
                    confidence,
                    json.dumps(source_tweets),
                ),
            )
        conn.commit()
        logger.info("Saved %d signal(s) for %s.", len(signals), run_date)
    finally:
        conn.close()


def summarize_history(history: list[dict]) -> dict[str, dict]:
    """
    Aggregate raw history rows into per-ticker summaries for prompt injection.

    Returns: {ticker: {"total": N, "actions": {"BUY": 3, "HOLD": 1, ...}, "last_seen": "date"}}
    """
    summaries: dict[str, dict] = {}
    for row in history:
        t = row["ticker"]
        if t not in summaries:
            summaries[t] = {"total": 0, "actions": {}, "last_seen": row["run_date"]}
        summaries[t]["total"] += 1
        action = row["action"]
        summaries[t]["actions"][action] = summaries[t]["actions"].get(action, 0) + 1
        # history is newest-first, so first occurrence = most recent
        if row["run_date"] > summaries[t]["last_seen"]:
            summaries[t]["last_seen"] = row["run_date"]
    return summaries
