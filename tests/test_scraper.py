import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import scraper


class StubClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def response(status_code, payload, *, headers=None):
    request = httpx.Request("GET", "https://api.x.com/test")
    return httpx.Response(status_code, json=payload, headers=headers, request=request)


def test_bearer_headers_requires_environment_variable(monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TWITTER_BEARER_TOKEN"):
        scraper._bearer_headers()


def test_fetch_tweets_today_resolves_user_and_maps_tweets(monkeypatch):
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "token")
    client = StubClient(
        [
            response(200, {"data": {"id": "42"}}),
            response(
                200,
                {
                    "data": [
                        {
                            "id": "100",
                            "text": "$NVDA is moving",
                            "created_at": "2026-09-03T10:00:00Z",
                        }
                    ],
                    "meta": {},
                },
            ),
        ]
    )

    tweets = asyncio.run(scraper.fetch_tweets_today(client, "analyst"))
    assert tweets[0].rawContent == "$NVDA is moving"
    assert tweets[0].url == "https://x.com/analyst/status/100"
    assert tweets[0].date.tzinfo is not None
    assert client.calls[1][1]["params"]["exclude"] == "retweets"


def test_fetch_tweets_today_retries_after_rate_limit(monkeypatch):
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "token")
    sleep = AsyncMock()
    monkeypatch.setattr(scraper.asyncio, "sleep", sleep)
    client = StubClient(
        [
            response(200, {"data": {"id": "42"}}),
            response(429, {}, headers={"x-rate-limit-reset": "0"}),
            response(200, {"data": [], "meta": {}}),
        ]
    )

    assert asyncio.run(scraper.fetch_tweets_today(client, "analyst")) == []
    sleep.assert_awaited_once_with(5)


def test_fetch_tweets_today_stops_after_repeated_rate_limits(monkeypatch):
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "token")
    monkeypatch.setattr(scraper.asyncio, "sleep", AsyncMock())
    client = StubClient(
        [
            response(200, {"data": {"id": "42"}}),
            *[
                response(429, {}, headers={"x-rate-limit-reset": "0"})
                for _ in range(scraper.MAX_RATE_LIMIT_RETRIES + 1)
            ],
        ]
    )

    with pytest.raises(scraper.TwitterFetchError, match="retries exhausted"):
        asyncio.run(scraper.fetch_tweets_today(client, "analyst"))


def test_fetch_all_isolates_one_users_failure(monkeypatch):
    fetch = AsyncMock(
        side_effect=[
            [scraper.Tweet(rawContent="ok", date=None, url="")],
            RuntimeError("X unavailable"),
        ]
    )
    monkeypatch.setattr(scraper, "fetch_tweets_today", fetch)

    class AsyncClientContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        scraper.httpx, "AsyncClient", lambda **kwargs: AsyncClientContext()
    )
    result = asyncio.run(scraper.fetch_all(["working", "broken"]))
    assert len(result["working"]) == 1
    assert result["broken"] == []


def test_fetch_all_raises_when_every_account_fails(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_tweets_today",
        AsyncMock(side_effect=RuntimeError("X unavailable")),
    )

    class AsyncClientContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        scraper.httpx, "AsyncClient", lambda **kwargs: AsyncClientContext()
    )
    with pytest.raises(scraper.TwitterFetchError, match="every account"):
        asyncio.run(scraper.fetch_all(["one", "two"]))
