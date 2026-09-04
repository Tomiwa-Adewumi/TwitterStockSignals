import sqlite3

import pytest

from analyzer import StockSignal
from database import (
    ActiveRunError,
    complete_run,
    create_run,
    database_is_ready,
    fail_run,
    finish_run,
    get_run,
    init_database,
    list_runs,
    list_signals,
    mark_run_started,
    persist_analysis,
    recover_incomplete_runs,
    summarize_history,
)


def test_run_lifecycle_and_signal_queries(tmp_path):
    db_path = str(tmp_path / "signals.db")
    init_database(db_path)
    run_id = create_run(db_path, "2026-09-03")
    mark_run_started(db_path, run_id)
    complete_run(
        db_path,
        run_id,
        "2026-09-03",
        [
            StockSignal(
                ticker="nvda",
                company_name="NVIDIA Corporation",
                action="buy",
                confidence="high",
                reasoning="Strong demand.",
                source_tweets=["https://x.com/example/status/1"],
            )
        ],
        "AI infrastructure remains strong.",
        12,
    )

    run = get_run(db_path, run_id)
    assert run["status"] == "completed"
    assert run["tweet_count"] == 12

    signals, total = list_signals(db_path, ticker="NvDa")
    assert total == 1
    assert signals[0]["ticker"] == "NVDA"
    assert signals[0]["company_name"] == "NVIDIA Corporation"
    assert signals[0]["source_tweet_urls"] == ["https://x.com/example/status/1"]


def test_legacy_schema_is_migrated(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY, run_date TEXT, ticker TEXT, action TEXT,
                reasoning TEXT, confidence TEXT, source_tweet_urls TEXT
            );
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY, run_date TEXT, summary TEXT, tweet_count INTEGER
            );
            """
        )

    init_database(db_path)
    with sqlite3.connect(db_path) as connection:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        signal_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(signals)")
        }
    assert {
        "status",
        "period",
        "started_at",
        "completed_at",
        "error",
        "email_requested",
        "email_error",
    } <= run_columns
    assert {"run_id", "company_name"} <= signal_columns


def test_active_run_guard_is_atomic(tmp_path):
    db_path = str(tmp_path / "signals.db")
    first_run = create_run(db_path, "2026-09-03", ensure_idle=True)
    with pytest.raises(ActiveRunError, match=str(first_run)):
        create_run(db_path, "2026-09-03", ensure_idle=True)

    fail_run(db_path, first_run, "cancelled")
    second_run = create_run(db_path, "2026-09-03", ensure_idle=True)
    assert second_run > first_run


def test_failure_state_is_persisted_and_error_is_bounded(tmp_path):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(db_path, "2026-09-03")
    mark_run_started(db_path, run_id)
    fail_run(db_path, run_id, "x" * 3000)
    run = get_run(db_path, run_id)
    assert run["status"] == "failed"
    assert len(run["error"]) == 2000
    assert run["completed_at"] is not None


def test_analysis_and_email_delivery_have_independent_state(tmp_path):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(db_path, "2026-09-03", email_requested=True)
    mark_run_started(db_path, run_id)
    persist_analysis(
        db_path,
        run_id,
        "2026-09-03",
        [{"ticker": "AAPL", "action": "BUY"}],
        "Saved analysis",
        2,
    )
    assert get_run(db_path, run_id)["status"] == "running"

    finish_run(db_path, run_id, email_error="SMTP unavailable")
    run = get_run(db_path, run_id)
    signals, total = list_signals(db_path)
    assert run["status"] == "completed"
    assert run["email_sent"] == 0
    assert run["email_error"] == "SMTP unavailable"
    assert total == 1
    assert signals[0]["ticker"] == "AAPL"


def test_replayed_analysis_replaces_signals_instead_of_duplicating(tmp_path):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(db_path, "2026-09-03")
    mark_run_started(db_path, run_id)
    for action in ("BUY", "HOLD"):
        persist_analysis(
            db_path,
            run_id,
            "2026-09-03",
            [{"ticker": "AAPL", "action": action}],
            "Replay-safe",
            1,
        )

    signals, total = list_signals(db_path, ticker="AAPL")
    assert total == 1
    assert signals[0]["action"] == "HOLD"


def test_recover_incomplete_runs_requeues_interrupted_work(tmp_path):
    db_path = str(tmp_path / "signals.db")
    running = create_run(db_path, "2026-09-03", email_requested=True)
    queued = create_run(db_path, "2026-09-03")
    mark_run_started(db_path, running)

    recovered = recover_incomplete_runs(db_path, stale_after_minutes=0)
    assert [run["id"] for run in recovered] == [running, queued]
    assert get_run(db_path, running)["status"] == "queued"


def test_signal_filters_and_pagination(tmp_path):
    db_path = str(tmp_path / "signals.db")
    for index, (ticker, action) in enumerate(
        [("AAPL", "BUY"), ("NVDA", "SELL"), ("AAPL", "HOLD")], start=1
    ):
        run_id = create_run(db_path, f"2026-09-0{index}")
        complete_run(
            db_path,
            run_id,
            f"2026-09-0{index}",
            [
                {
                    "ticker": ticker,
                    "action": action,
                    "confidence": "HIGH",
                    "source_tweets": [],
                }
            ],
            "summary",
            index,
        )

    aapl, total = list_signals(db_path, ticker="aapl", limit=1)
    assert total == 2
    assert len(aapl) == 1
    assert aapl[0]["action"] == "HOLD"
    second_page, _ = list_signals(db_path, ticker="AAPL", limit=1, offset=1)
    assert second_page[0]["action"] == "BUY"
    sells, total = list_signals(db_path, action="sell")
    assert total == 1
    assert sells[0]["ticker"] == "NVDA"

    runs, run_total = list_runs(db_path, limit=2, offset=1)
    assert run_total == 3
    assert len(runs) == 2


def test_history_summary_counts_actions_and_latest_date():
    rows = [
        {"ticker": "AAPL", "action": "BUY", "run_date": "2026-09-01"},
        {"ticker": "AAPL", "action": "HOLD", "run_date": "2026-09-03"},
        {"ticker": "NVDA", "action": "BUY", "run_date": "2026-09-02"},
    ]
    summary = summarize_history(rows)
    assert summary["AAPL"] == {
        "total": 2,
        "actions": {"BUY": 1, "HOLD": 1},
        "last_seen": "2026-09-03",
    }


def test_database_health_reports_invalid_database_path(tmp_path):
    directory = tmp_path / "not-a-database"
    directory.mkdir()
    assert database_is_ready(str(directory)) is False
