"""Reusable orchestration for the stock-signal pipeline."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from analyzer import AnalysisResult, analyze_tweets, extract_tickers
from database import (
    create_run,
    fail_run,
    finish_run,
    get_history,
    mark_run_started,
    persist_analysis,
    summarize_history,
)
from emailer import build_html, send_digest
from researcher import research_tickers
from scraper import fetch_all

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised after analysis is saved but requested delivery fails."""


@dataclass
class PipelineResult:
    run_id: int
    status: str
    summary: str
    tweet_count: int
    signal_count: int
    email_sent: bool
    html: str


def format_tweets_for_prompt(tweet_map: dict) -> str:
    """Flatten fetched tweets into the format consumed by the analyzer."""
    lines = []
    for username, tweets in tweet_map.items():
        for tweet in tweets:
            text = (
                getattr(tweet, "rawContent", None)
                or getattr(tweet, "content", None)
                or str(tweet)
            )
            url = getattr(tweet, "url", "") or ""
            date_str = (
                tweet.date.strftime("%Y-%m-%d %H:%M UTC")
                if hasattr(tweet, "date") and tweet.date
                else ""
            )
            lines.append(f"@{username} [{date_str}]: {text}")
            if url:
                lines.append(f"  Source: {url}")
    return "\n".join(lines)


async def execute_pipeline(
    config: dict,
    db_path: str,
    *,
    period: str = "today",
    send_email: bool = False,
    run_id: int | None = None,
) -> PipelineResult:
    """Execute one pipeline run and persist its lifecycle."""
    run_date = datetime.now(timezone.utc).date().isoformat()
    run_id = run_id or create_run(db_path, run_date, period)
    mark_run_started(db_path, run_id)
    logger.info("Starting pipeline run %d for %s", run_id, run_date)

    try:
        tweet_map = await fetch_all(config["users"])
        tweet_count = sum(len(tweets) for tweets in tweet_map.values())
        history_summary: dict = {}
        analysis: AnalysisResult

        if tweet_count == 0:
            analysis = AnalysisResult(
                summary="No tweets found today from any configured user.", signals=[]
            )
        else:
            tweet_text = format_tweets_for_prompt(tweet_map)
            tickers = extract_tickers(tweet_text, config)
            if not tickers:
                analysis = AnalysisResult(
                    summary="No stock tickers found in today's tweets.", signals=[]
                )
            else:
                research = research_tickers(tickers)
                history = get_history(
                    db_path, days=int(config.get("ai", {}).get("history_days", 30))
                )
                history_summary = summarize_history(history)
                analysis = analyze_tweets(tweet_text, research, history_summary, config)

        # Save the valuable analysis before rendering or external delivery.
        # The run remains active until all requested work has finished.
        persist_analysis(
            db_path,
            run_id,
            run_date,
            analysis.signals,
            analysis.summary,
            tweet_count,
        )

        weekly_rollup = None
        if period == "this week":
            weekly_rollup = summarize_history(get_history(db_path, days=7))
        html = build_html(tweet_map, analysis, history_summary, period, weekly_rollup)

        email_sent = False
        if send_email:
            try:
                send_digest(html, analysis, tweet_map, config)
                email_sent = True
            except Exception as exc:
                finish_run(db_path, run_id, email_error=str(exc))
                raise EmailDeliveryError(
                    f"Analysis saved, but email delivery failed: {exc}"
                ) from exc

        finish_run(db_path, run_id, email_sent=email_sent)
        return PipelineResult(
            run_id=run_id,
            status="completed",
            summary=analysis.summary,
            tweet_count=tweet_count,
            signal_count=len(analysis.signals),
            email_sent=email_sent,
            html=html,
        )
    except EmailDeliveryError:
        raise
    except Exception as exc:
        logger.exception("Pipeline run %d failed", run_id)
        fail_run(db_path, run_id, str(exc))
        raise
