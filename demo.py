"""Credential-free synthetic pipeline demonstration; no network or email delivery."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock, patch

from analyzer import AnalysisResult, StockSignal
from database import get_run, list_signals
from pipeline import execute_pipeline
from scraper import Tweet


def main():
    signal = StockSignal(
        ticker="DEMO",
        company_name="Synthetic Example",
        action="INVESTIGATE",
        confidence="LOW",
        reasoning="Synthetic fixture, not market research.",
        source_tweets=[],
    )
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "demo.db")
        with (
            patch(
                "pipeline.fetch_all",
                new=AsyncMock(
                    return_value={
                        "demo": [
                            Tweet(
                                "$DEMO fixture",
                                datetime(2026, 1, 1, tzinfo=timezone.utc),
                                "https://example.com/fixture",
                            )
                        ]
                    }
                ),
            ),
            patch("pipeline.extract_tickers", return_value=["DEMO"]),
            patch("pipeline.research_tickers", return_value={}),
            patch(
                "pipeline.analyze_tweets",
                return_value=AnalysisResult(summary="Synthetic demo", signals=[signal]),
            ),
            patch("pipeline.send_digest") as delivery,
        ):
            start = perf_counter()
            result = asyncio.run(
                execute_pipeline({"users": ["demo"], "ai": {}, "email": {}}, db_path)
            )
            elapsed = perf_counter() - start
            assert not delivery.called
        items, total = list_signals(db_path)
        print(
            json.dumps(
                {
                    "kind": "synthetic-offline-demo",
                    "elapsed_seconds": round(elapsed, 6),
                    "run": get_run(db_path, result.run_id),
                    "signal_count": total,
                    "signals": items,
                },
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
