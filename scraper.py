"""
scraper.py — Fetch today's tweets from configured Twitter/X users via twscrape.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import twscrape
from twscrape import API, gather
from twscrape.logger import set_log_level

set_log_level("WARNING")
logger = logging.getLogger(__name__)


async def ensure_account_seeded(api: API) -> None:
    """Seed a Twitter account from TWS_COOKIES env var if no accounts exist.

    twscrape attempts a fresh login flow (parsing Twitter's JS) even when cookies
    are provided. That flow often fails ('Failed to parse scripts') and locks the
    account. We reset locks immediately so subsequent requests use the cookies
    directly rather than re-attempting the login flow.
    """
    accounts = await api.pool.get_all()
    if accounts:
        # Clear any stale locks from a previous run's failed login attempt.
        await api.pool.reset_locks()
        logger.info("Existing account found; locks reset.")
        return

    cookies_json = os.environ.get("TWS_COOKIES", "")
    if not cookies_json:
        logger.warning("TWS_COOKIES not set; scraping may fail without an account.")
        return

    try:
        json.loads(cookies_json)
    except json.JSONDecodeError:
        logger.error("TWS_COOKIES is not valid JSON.")
        return

    username = os.environ.get("TWS_USERNAME", "")
    password = os.environ.get("TWS_PASSWORD", "")
    email = os.environ.get("TWS_EMAIL", "")
    email_password = os.environ.get("TWS_EMAIL_PASSWORD", "")

    if not username:
        logger.error("TWS_USERNAME not set; cannot seed account.")
        return

    try:
        await api.pool.add_account(
            username=username,
            password=password,
            email=email,
            email_password=email_password,
            cookies=cookies_json,
        )
    except Exception as exc:
        # add_account may raise if the login flow fails; this is expected when
        # Twitter's JS changes. Reset locks so the cookie session can still be used.
        logger.warning("add_account raised (login flow failed, expected): %s", exc)

    # Reset any lock that was set by the failed login verification.
    await api.pool.reset_locks()
    logger.info("Seeded Twitter account: %s", username)


async def fetch_tweets_today(api: API, username: str) -> list:
    """Fetch tweets posted since UTC midnight today for a given user."""
    midnight_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    tweets = []
    try:
        async for tweet in api.user_tweets(
            await _get_user_id(api, username), limit=100
        ):
            if tweet.date < midnight_utc:
                break
            tweets.append(tweet)
    except twscrape.NoAccountError:
        logger.error("No valid Twitter account available. Check TWS_COOKIES.")
        raise
    except Exception as exc:
        logger.warning("Failed to fetch tweets for @%s: %s", username, exc)

    logger.info("Fetched %d tweet(s) from @%s today.", len(tweets), username)
    return tweets


async def _get_user_id(api: API, username: str) -> int:
    """Resolve a username to a Twitter user ID."""
    user = await api.user_by_login(username)
    if user is None:
        raise ValueError(f"User @{username} not found or is private.")
    return user.id


async def fetch_all(usernames: list[str], db_path: str) -> dict[str, list]:
    """
    Fetch today's tweets for all configured users.

    Returns: {"username": [Tweet, ...], ...}
    """
    api = API(db_path)
    await ensure_account_seeded(api)

    tweet_map: dict[str, list] = {}
    for username in usernames:
        try:
            tweets = await fetch_tweets_today(api, username)
            tweet_map[username] = tweets
        except twscrape.NoAccountError:
            raise
        except Exception as exc:
            logger.warning("Skipping @%s due to error: %s", username, exc)
            tweet_map[username] = []

    return tweet_map
