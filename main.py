"""
main.py — Pipeline orchestration entry point for the Twitter Stock Digest.

Usage:
    python main.py                   # Full run: fetch → analyze → email
    python main.py --dry-run         # Print HTML instead of emailing
    python main.py --weekly          # Label period as "this week"
    python main.py --config PATH     # Use a custom config file
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

import yaml
from dotenv import load_dotenv

from analyzer import AnalysisResult, analyze_tweets, extract_tickers
from database import get_history, save_signals, summarize_history
from emailer import build_html, send_digest
from researcher import research_tickers
from scraper import fetch_all

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = "signals.db"


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def format_tweets_for_prompt(tweet_map: dict) -> str:
    """Flatten all tweets into a single string for Claude prompts."""
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


async def run(config: dict, period: str, dry_run: bool, weekly: bool = False) -> None:
    today = date.today().isoformat()
    logger.info("Starting digest run for %s (period=%s, dry_run=%s)", today, period, dry_run)

    # 1. Fetch tweets
    logger.info("Step 1/7: Fetching tweets...")
    try:
        tweet_map = await fetch_all(config["users"])
    except Exception as exc:
        logger.error("Fatal: tweet fetch failed: %s", exc)
        sys.exit(1)

    tweet_count = sum(len(v) for v in tweet_map.values())
    logger.info("Fetched %d total tweet(s) across %d user(s).", tweet_count, len(tweet_map))

    if tweet_count == 0:
        logger.warning("No tweets found today. Sending notice email.")
        no_tweets_analysis = AnalysisResult(
            summary="No tweets found today from any configured user.",
            signals=[],
        )
        html = build_html(tweet_map, no_tweets_analysis, {}, period)
        if dry_run:
            print(html)
        else:
            send_digest(html, no_tweets_analysis, tweet_map, config)
        return

    tweet_text = format_tweets_for_prompt(tweet_map)

    # 2. Extract tickers
    logger.info("Step 2/7: Extracting tickers with Claude...")
    tickers = extract_tickers(tweet_text, config)
    logger.info("Found tickers: %s", tickers or "(none)")

    if not tickers:
        logger.warning("No tickers found. Emailing raw tweets only.")
        no_ticker_analysis = AnalysisResult(
            summary="No stock tickers found in today's tweets.",
            signals=[],
        )
        html = build_html(tweet_map, no_ticker_analysis, {}, period)
        if dry_run:
            print(html)
        else:
            send_digest(html, no_ticker_analysis, tweet_map, config)
        return

    # 3. Research tickers
    logger.info("Step 3/7: Researching %d ticker(s)...", len(tickers))
    research = research_tickers(tickers)

    # 4. Load signal history
    logger.info("Step 4/7: Loading signal history...")
    history_rows = get_history(DB_PATH, days=config["ai"]["history_days"])
    history_summary = summarize_history(history_rows)
    logger.info("Loaded %d historical signal(s) for context.", len(history_rows))

    # 5. Analyze with Claude
    logger.info("Step 5/7: Analyzing with Claude...")
    analysis = analyze_tweets(tweet_text, research, history_summary, config)
    logger.info(
        "Analysis complete: %d signal(s). Summary: %s",
        len(analysis.signals),
        analysis.summary[:80],
    )

    # 6. Save signals + will be committed by GitHub Actions
    logger.info("Step 6/7: Saving signals to %s...", DB_PATH)
    save_signals(
        DB_PATH,
        today,
        analysis.signals,
        analysis.summary,
        tweet_count,
    )

    # 7. Build email and send (or print)
    logger.info("Step 7/7: Building and sending email...")
    weekly_rollup = None
    if weekly:
        weekly_rows = get_history(DB_PATH, days=7)
        weekly_rollup = summarize_history(weekly_rows)
    html = build_html(tweet_map, analysis, history_summary, period, weekly_rollup)
    if dry_run:
        print(html)
        logger.info("Dry run: HTML printed to stdout.")
    else:
        send_digest(html, analysis, tweet_map, config)
        logger.info("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter Stock Digest")
    parser.add_argument("--dry-run", action="store_true", help="Print HTML, don't email")
    parser.add_argument("--weekly", action="store_true", help="Label digest as weekly")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)
    period = "this week" if args.weekly else "today"

    asyncio.run(run(config, period, args.dry_run, weekly=args.weekly))


if __name__ == "__main__":
    main()
