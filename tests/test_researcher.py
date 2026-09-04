from unittest.mock import Mock

import researcher


def test_get_stock_data_selects_supported_yfinance_fields(monkeypatch):
    ticker = Mock()
    ticker.info = {
        "shortName": "NVIDIA",
        "currentPrice": 123.45,
        "unsupported": "ignored",
        "forwardPE": None,
    }
    ticker_factory = Mock(return_value=ticker)
    monkeypatch.setattr(researcher.yf, "Ticker", ticker_factory)

    result = researcher.get_stock_data("NVDA")
    assert result == {"shortName": "NVIDIA", "currentPrice": 123.45}
    ticker_factory.assert_called_once_with("NVDA")


def test_get_stock_data_contains_provider_failure(monkeypatch):
    monkeypatch.setattr(
        researcher.yf, "Ticker", Mock(side_effect=RuntimeError("provider down"))
    )
    assert researcher.get_stock_data("NVDA") == {}


def test_get_news_headlines_formats_duckduckgo_results(monkeypatch):
    ddgs = Mock()
    ddgs.news.return_value = [
        {
            "title": "Chip demand rises",
            "source": "Example News",
            "date": "2026-09-03T10:00:00Z",
        }
    ]
    monkeypatch.setattr(researcher, "DDGS", Mock(return_value=ddgs))

    assert researcher.get_news_headlines("NVDA") == [
        "Chip demand rises — Example News (2026-09-03)"
    ]
    ddgs.news.assert_called_once_with("NVDA stock", max_results=10)


def test_research_tickers_combines_sources_and_throttles(monkeypatch):
    stock = Mock(side_effect=lambda ticker: {"shortName": ticker})
    news = Mock(side_effect=lambda ticker: [f"{ticker} headline"])
    sleep = Mock()
    monkeypatch.setattr(researcher, "get_stock_data", stock)
    monkeypatch.setattr(researcher, "get_news_headlines", news)
    monkeypatch.setattr(researcher.time, "sleep", sleep)

    result = researcher.research_tickers(["AAPL", "NVDA"])
    assert result["AAPL"]["price_data"] == {"shortName": "AAPL"}
    assert result["NVDA"]["headlines"] == ["NVDA headline"]
    sleep.assert_called_once_with(1)
