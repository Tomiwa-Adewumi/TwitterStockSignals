"""
scraper.py — Fetch today's tweets via X API v2 (Bearer Token auth).
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.x.com/2"
MAX_RESULTS = 100  # max per page for user timeline


@dataclass
class Tweet:
    """Minimal tweet object matching attributes used in main.py."""
    rawContent: str
    date: datetime
    url: str


def _bearer_headers() -> dict:
    token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        raise RuntimeError("TWITTER_BEARER_TOKEN env var not set.")
    return {"Authorization": f"Bearer {token}"}


async def _get_user_id(client: httpx.AsyncClient, username: str) -> str:
    """Resolve username → user ID via GET /2/users/by/username/:username"""
    resp = await client.get(
        f"{BASE_URL}/users/by/username/{username}",
        headers=_bearer_headers(),
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data or "data" not in data:
        raise ValueError(f"User @{username} not found: {data}")
    return data["data"]["id"]


async def fetch_tweets_today(client: httpx.AsyncClient, username: str) -> list[Tweet]:
    """Fetch tweets from the last 24 hours for a user."""
    start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        user_id = await _get_user_id(client, username)
    except Exception as exc:
        logger.warning("Could not resolve @%s: %s", username, exc)
        return []

    tweets: list[Tweet] = []
    pagination_token: str | None = None

    while True:
        params: dict = {
            "start_time": start_time,
            "max_results": MAX_RESULTS,
            "tweet.fields": "created_at,text",
            "exclude": "retweets",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        try:
            resp = await client.get(
                f"{BASE_URL}/users/{user_id}/tweets",
                headers=_bearer_headers(),
                params=params,
            )
            if resp.status_code == 429:
                reset = int(resp.headers.get("x-rate-limit-reset", 0))
                wait = max(reset - int(datetime.now(timezone.utc).timestamp()), 5)
                logger.warning("Rate limited; waiting %ds", wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP error for @%s: %s", username, exc)
            break

        body = resp.json()
        items = body.get("data") or []
        for item in items:
            created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
            url = f"https://x.com/{username}/status/{item['id']}"
            tweets.append(Tweet(rawContent=item["text"], date=created, url=url))

        pagination_token = body.get("meta", {}).get("next_token")
        if not pagination_token:
            break

    logger.info("Fetched %d tweet(s) from @%s today.", len(tweets), username)
    return tweets


async def fetch_all(usernames: list[str]) -> dict[str, list[Tweet]]:
    """Fetch today's tweets for all configured users."""
    tweet_map: dict[str, list[Tweet]] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for username in usernames:
            try:
                tweets = await fetch_tweets_today(client, username)
                tweet_map[username] = tweets
            except Exception as exc:
                logger.warning("Skipping @%s due to error: %s", username, exc)
                tweet_map[username] = []
    return tweet_map
