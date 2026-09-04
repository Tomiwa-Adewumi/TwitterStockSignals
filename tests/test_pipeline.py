import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import analyzer
import pipeline
import researcher
from analyzer import AnalysisResult, StockSignal
from database import get_run, list_signals
from scraper import Tweet


def test_format_tweets_for_prompt_includes_identity_time_and_source():
    tweet = Tweet(
        rawContent="$AAPL looks interesting",
        date=datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc),
        url="https://x.com/analyst/status/1",
    )
    text = pipeline.format_tweets_for_prompt({"analyst": [tweet]})
    assert "@analyst [2026-09-03 10:30 UTC]" in text
    assert "$AAPL looks interesting" in text
    assert "Source: https://x.com/analyst/status/1" in text


def test_end_to_end_pipeline_with_all_external_services_mocked(tmp_path, monkeypatch):
    """Exercise X -> Claude -> research -> SQLite -> HTML/email as one flow."""
    tweet_url = "https://x.com/analyst/status/1"

    async def fake_fetch_all(users):
        assert users == ["analyst"]
        return {
            "analyst": [
                Tweet(
                    rawContent="$NVDA demand is accelerating",
                    date=datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc),
                    url=tweet_url,
                )
            ]
        }

    monkeypatch.setattr(pipeline, "fetch_all", fake_fetch_all)

    claude = Mock()
    claude.messages.create.side_effect = [
        SimpleNamespace(
            content=[SimpleNamespace(text='["NVDA"]')],
            stop_reason="end_turn",
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "summary": "AI infrastructure demand remains strong.",
                            "signals": [
                                {
                                    "ticker": "NVDA",
                                    "action": "BUY",
                                    "confidence": "HIGH",
                                    "reasoning": "Demand and fundamentals agree.",
                                    "source_tweets": [tweet_url],
                                }
                            ],
                        }
                    )
                )
            ],
            stop_reason="end_turn",
        ),
    ]
    monkeypatch.setattr(analyzer, "_client", lambda config: claude)

    yfinance_ticker = Mock()
    yfinance_ticker.info = {
        "shortName": "NVIDIA Corporation",
        "currentPrice": 200,
        "revenueGrowth": 0.5,
    }
    monkeypatch.setattr(researcher.yf, "Ticker", Mock(return_value=yfinance_ticker))
    ddgs = Mock()
    ddgs.news.return_value = [
        {
            "title": "NVIDIA demand rises",
            "source": "Wire",
            "date": "2026-09-03",
        }
    ]
    monkeypatch.setattr(researcher, "DDGS", Mock(return_value=ddgs))
    send_digest = Mock()
    monkeypatch.setattr(pipeline, "send_digest", send_digest)

    db_path = str(tmp_path / "signals.db")
    result = asyncio.run(
        pipeline.execute_pipeline(
            {
                "users": ["analyst"],
                "ai": {"model": "claude-test", "history_days": 30},
                "email": {},
            },
            db_path,
            send_email=True,
        )
    )

    assert result.status == "completed"
    assert result.tweet_count == 1
    assert result.signal_count == 1
    assert "NVIDIA Corporation" in result.html
    assert get_run(db_path, result.run_id)["email_sent"] == 1
    signals, total = list_signals(db_path, ticker="NVDA")
    assert total == 1
    assert signals[0]["source_tweet_urls"] == [tweet_url]
    send_digest.assert_called_once()
    assert claude.messages.create.call_count == 2


def test_pipeline_marks_run_failed_when_fetch_raises(tmp_path, monkeypatch):
    async def failed_fetch(_users):
        raise RuntimeError("X credentials rejected")

    monkeypatch.setattr(pipeline, "fetch_all", failed_fetch)
    db_path = str(tmp_path / "signals.db")

    try:
        asyncio.run(
            pipeline.execute_pipeline(
                {"users": ["analyst"], "ai": {"model": "test"}},
                db_path,
            )
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("Pipeline should propagate fatal failures")

    run = get_run(db_path, 1)
    assert run["status"] == "failed"
    assert "credentials rejected" in run["error"]


def configure_single_signal_pipeline(monkeypatch):
    async def fetch(_users):
        return {
            "analyst": [
                Tweet(
                    "$AAPL",
                    datetime(2026, 9, 3, tzinfo=timezone.utc),
                    "https://x.com/a/1",
                )
            ]
        }

    monkeypatch.setattr(pipeline, "fetch_all", fetch)
    monkeypatch.setattr(pipeline, "extract_tickers", lambda *_args: ["AAPL"])
    monkeypatch.setattr(
        pipeline,
        "research_tickers",
        lambda _tickers: {"AAPL": {"price_data": {"shortName": "Apple"}}},
    )
    monkeypatch.setattr(
        pipeline,
        "analyze_tweets",
        lambda *_args: AnalysisResult(
            "Apple remains constructive.",
            [StockSignal("AAPL", "Apple", "BUY", "HIGH", "Strong demand.", [])],
        ),
    )


def test_email_failure_preserves_analysis_and_delivery_error(tmp_path, monkeypatch):
    configure_single_signal_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "send_digest",
        Mock(side_effect=RuntimeError("SMTP unavailable")),
    )
    db_path = str(tmp_path / "signals.db")

    with pytest.raises(pipeline.EmailDeliveryError):
        asyncio.run(
            pipeline.execute_pipeline(
                {
                    "users": ["analyst"],
                    "ai": {"model": "test"},
                    "email": {},
                },
                db_path,
                send_email=True,
            )
        )

    run = get_run(db_path, 1)
    signals, total = list_signals(db_path, ticker="AAPL")
    assert run["status"] == "completed"
    assert run["email_sent"] == 0
    assert "SMTP unavailable" in run["email_error"]
    assert total == 1
    assert signals[0]["reasoning"] == "Strong demand."


def test_weekly_rollup_includes_current_run(tmp_path, monkeypatch):
    configure_single_signal_pipeline(monkeypatch)
    html_builder = Mock(return_value="<html></html>")
    monkeypatch.setattr(pipeline, "build_html", html_builder)

    asyncio.run(
        pipeline.execute_pipeline(
            {"users": ["analyst"], "ai": {"model": "test"}},
            str(tmp_path / "signals.db"),
            period="this week",
        )
    )

    weekly_rollup = html_builder.call_args.args[4]
    assert weekly_rollup["AAPL"]["actions"]["BUY"] == 1


def test_no_tweets_completes_without_calling_anthropic(tmp_path, monkeypatch):
    async def fetch(_users):
        return {"analyst": []}

    extraction = Mock()
    monkeypatch.setattr(pipeline, "fetch_all", fetch)
    monkeypatch.setattr(pipeline, "extract_tickers", extraction)

    result = asyncio.run(
        pipeline.execute_pipeline(
            {"users": ["analyst"], "ai": {"model": "test"}},
            str(tmp_path / "signals.db"),
        )
    )

    assert result.status == "completed"
    assert result.signal_count == 0
    assert "No tweets found" in result.summary
    extraction.assert_not_called()


def test_no_tickers_completes_without_research(tmp_path, monkeypatch):
    async def fetch(_users):
        return {
            "analyst": [
                Tweet(
                    "No companies today",
                    datetime(2026, 9, 3, tzinfo=timezone.utc),
                    "",
                )
            ]
        }

    research = Mock()
    monkeypatch.setattr(pipeline, "fetch_all", fetch)
    monkeypatch.setattr(pipeline, "extract_tickers", lambda *_args: [])
    monkeypatch.setattr(pipeline, "research_tickers", research)

    result = asyncio.run(
        pipeline.execute_pipeline(
            {"users": ["analyst"], "ai": {"model": "test"}},
            str(tmp_path / "signals.db"),
        )
    )

    assert result.signal_count == 0
    assert "No stock tickers" in result.summary
    research.assert_not_called()
