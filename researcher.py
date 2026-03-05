"""
researcher.py — Per-ticker research via yfinance (fundamentals) and DuckDuckGo (news).
"""

import logging
import time

import yfinance as yf
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

_YFINANCE_FIELDS = [
    "shortName",
    "currentPrice",
    "previousClose",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "targetMeanPrice",
    "recommendationKey",
    "marketCap",
    "earningsGrowth",
    "revenueGrowth",
    "grossMargins",
    "operatingMargins",
    "returnOnEquity",
    "debtToEquity",
    "sector",
    "industry",
]


def get_stock_data(ticker: str) -> dict:
    """
    Fetch key fundamentals for a ticker via yfinance.

    Returns a dict of selected fields, or {} on failure.
    """
    try:
        info = yf.Ticker(ticker).info
        return {k: info.get(k) for k in _YFINANCE_FIELDS if info.get(k) is not None}
    except Exception as exc:
        logger.warning("yfinance lookup failed for %s: %s", ticker, exc)
        return {}


def get_news_headlines(ticker: str, max_results: int = 10) -> list[str]:
    """
    Fetch recent news headlines for a ticker via DuckDuckGo.

    Returns a list of "title — source (date)" strings, or [] on failure.
    """
    try:
        results = DDGS().news(f"{ticker} stock", max_results=max_results)
        headlines = []
        for r in results:
            date = r.get("date", "")[:10] if r.get("date") else ""
            source = r.get("source", "")
            title = r.get("title", "")
            parts = [title]
            if source:
                parts.append(f"— {source}")
            if date:
                parts.append(f"({date})")
            headlines.append(" ".join(parts))
        return headlines
    except Exception as exc:
        logger.warning("DuckDuckGo news failed for %s: %s", ticker, exc)
        return []


def research_tickers(tickers: list[str]) -> dict[str, dict]:
    """
    Research each ticker: fundamentals + news headlines.

    Sleeps 1s between tickers to respect rate limits.
    Returns: {ticker: {"price_data": {...}, "headlines": [...]}}
    """
    results: dict[str, dict] = {}
    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(1)
        logger.info("Researching %s...", ticker)
        results[ticker] = {
            "price_data": get_stock_data(ticker),
            "headlines": get_news_headlines(ticker),
        }
    return results
