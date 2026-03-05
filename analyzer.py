"""
analyzer.py — Claude-powered ticker extraction and investment signal analysis.
"""

import json
import logging
import os
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger(__name__)


@dataclass
class StockSignal:
    ticker: str
    company_name: str    # populated from research["price_data"]["shortName"]
    action: str          # BUY | SELL | HOLD | INVESTIGATE
    confidence: str      # HIGH | MEDIUM | LOW
    reasoning: str
    source_tweets: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    summary: str
    signals: list[StockSignal] = field(default_factory=list)


def _client(config: dict) -> anthropic.Anthropic:
    return anthropic.Anthropic()


def extract_tickers(tweet_text: str, config: dict) -> list[str]:
    """
    Call Claude to extract stock tickers mentioned in tweets.

    Returns a list of uppercase ticker strings, e.g. ["AAPL", "NVDA"].
    """
    if not tweet_text.strip():
        return []

    prompt = (
        "Given these tweets, list every stock ticker symbol mentioned "
        "(e.g. AAPL, NVDA, TSLA). If a company name is mentioned but not the ticker, "
        "infer the ticker. Return ONLY a JSON array of uppercase ticker strings: "
        '[\"AAPL\", \"NVDA\"]\nIf no stocks are mentioned, return [].\n\n'
        f"Tweets:\n{tweet_text}"
    )

    try:
        client = _client(config)
        response = client.messages.create(
            model=config["ai"]["model"],
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        tickers = json.loads(raw)
        if isinstance(tickers, list):
            return [t.upper() for t in tickers if isinstance(t, str)]
        return []
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse ticker JSON from Claude: %s", exc)
        return []
    except Exception as exc:
        logger.error("Ticker extraction failed: %s", exc)
        return []


def _format_research(research: dict[str, dict]) -> str:
    lines = []
    for ticker, data in research.items():
        lines.append(f"\n### {ticker}")
        price = data.get("price_data", {})
        if price:
            lines.append("**Fundamentals:**")
            for k, v in price.items():
                lines.append(f"  {k}: {v}")
        headlines = data.get("headlines", [])
        if headlines:
            lines.append("**Recent News:**")
            for h in headlines:
                lines.append(f"  - {h}")
    return "\n".join(lines)


def _format_history(history_summary: dict[str, dict]) -> str:
    if not history_summary:
        return "No prior signal history available."
    lines = []
    for ticker, info in history_summary.items():
        action_breakdown = ", ".join(
            f"{a}×{n}" for a, n in sorted(info["actions"].items())
        )
        lines.append(
            f"  {ticker}: {info['total']} signal(s) in history "
            f"[{action_breakdown}], last seen {info['last_seen']}"
        )
    return "\n".join(lines)


def analyze_tweets(
    tweet_text: str,
    research: dict[str, dict],
    history_summary: dict[str, dict],
    config: dict,
) -> AnalysisResult:
    """
    Call Claude to produce BUY/SELL/HOLD/INVESTIGATE signals.

    Returns an AnalysisResult with signals and a narrative summary.
    """
    if not research:
        return AnalysisResult(
            summary="No tickers found in today's tweets; no analysis performed.",
            signals=[],
        )

    tickers_list = ", ".join(research.keys())
    research_text = _format_research(research)
    history_text = _format_history(history_summary)

    criteria_path = os.path.join(os.path.dirname(__file__), "analysis_criteria.md")
    criteria_section = ""
    if os.path.exists(criteria_path):
        with open(criteria_path) as f:
            criteria_section = f"\n\n## Custom Analysis Criteria\n{f.read()}"

    prompt = f"""You are an expert stock analyst. Analyze the following tweets and research data to produce actionable investment signals.

## Today's Tweets
{tweet_text}

## Research Data for Tickers: {tickers_list}
{research_text}

## Historical Signals (last 30 days)
{history_text}

## Instructions
For each ticker ({tickers_list}), produce one of: BUY, SELL, HOLD, or INVESTIGATE.{criteria_section}
- BUY: Strong positive sentiment + supportive fundamentals/news
- SELL: Strong negative sentiment or concerning fundamentals
- HOLD: Mixed or neutral signals
- INVESTIGATE: Interesting mention but insufficient data to act

Return ONLY valid JSON in this exact structure:
{{
  "summary": "2-3 sentence market narrative covering the key themes today",
  "signals": [
    {{
      "ticker": "AAPL",
      "action": "BUY",
      "confidence": "HIGH",
      "reasoning": "1-2 sentences grounded in the tweets and research above",
      "source_tweets": ["url1", "url2"]
    }}
  ]
}}
"""

    try:
        client = _client(config)
        response = client.messages.create(
            model=config["ai"]["model"],
            max_tokens=config["ai"]["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        signals = []
        for s in data.get("signals", []):
            ticker = s.get("ticker", "").upper()
            company_name = research.get(ticker, {}).get("price_data", {}).get("shortName", "")
            signals.append(
                StockSignal(
                    ticker=ticker,
                    company_name=company_name,
                    action=s.get("action", "INVESTIGATE").upper(),
                    confidence=s.get("confidence", "LOW").upper(),
                    reasoning=s.get("reasoning", ""),
                    source_tweets=s.get("source_tweets", []),
                )
            )

        return AnalysisResult(
            summary=data.get("summary", ""),
            signals=signals,
        )

    except json.JSONDecodeError as exc:
        logger.error("Failed to parse analysis JSON from Claude: %s", exc)
        return AnalysisResult(
            summary="Analysis unavailable (JSON parse error).",
            signals=[],
        )
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        return AnalysisResult(
            summary=f"Analysis unavailable ({exc}).",
            signals=[],
        )
