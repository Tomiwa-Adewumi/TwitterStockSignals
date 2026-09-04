import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import analyzer


def claude_response(payload, *, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        stop_reason=stop_reason,
    )


def mocked_client(monkeypatch, *responses):
    client = Mock()
    client.messages.create.side_effect = responses
    monkeypatch.setattr(analyzer, "_client", lambda config: client)
    return client


def test_extract_json_handles_fences_nested_objects_and_braces_in_strings():
    text = 'prefix ```json\n{"outer": {"text": "a } brace"}, "ok": true}\n``` suffix'
    assert json.loads(analyzer._extract_json(text))["outer"]["text"] == "a } brace"


def test_extract_tickers_skips_network_for_empty_input(monkeypatch):
    client_factory = Mock()
    monkeypatch.setattr(analyzer, "_client", client_factory)
    assert analyzer.extract_tickers("  ", {"ai": {"model": "test"}}) == []
    client_factory.assert_not_called()


def test_extract_tickers_uses_anthropic_and_normalizes_symbols(monkeypatch):
    client = mocked_client(
        monkeypatch,
        claude_response('Result: ["nvda", " AAPL ", "NVDA", "not valid", 123]'),
    )
    result = analyzer.extract_tickers(
        "Nvidia and Apple look strong", {"ai": {"model": "claude-test"}}
    )
    assert result == ["NVDA", "AAPL"]
    call = client.messages.create.call_args.kwargs
    assert call["model"] == "claude-test"
    assert "Nvidia and Apple" in call["messages"][0]["content"]


def test_extract_tickers_returns_empty_list_for_invalid_claude_json(monkeypatch):
    mocked_client(monkeypatch, claude_response("not json"))
    with pytest.raises(analyzer.AnalysisProviderError, match="invalid JSON"):
        analyzer.extract_tickers("some tweet", {"ai": {"model": "test"}})


def test_analyze_tweets_maps_research_and_history_into_signal(monkeypatch):
    client = mocked_client(
        monkeypatch,
        claude_response(
            {
                "summary": "Chip demand is strong.",
                "signals": [
                    {
                        "ticker": "nvda",
                        "action": "buy",
                        "confidence": "high",
                        "reasoning": "Revenue growth is accelerating.",
                        "source_tweets": ["https://x.com/user/status/1"],
                    }
                ],
            }
        ),
    )
    research = {
        "NVDA": {
            "price_data": {"shortName": "NVIDIA Corporation", "currentPrice": 100},
            "headlines": ["NVIDIA reports results"],
        }
    }
    history = {"NVDA": {"total": 2, "actions": {"BUY": 2}, "last_seen": "2026-09-02"}}

    result = analyzer.analyze_tweets(
        "@user: NVDA", research, history, {"ai": {"model": "test", "max_tokens": 1000}}
    )
    assert result.summary == "Chip demand is strong."
    assert result.signals[0].company_name == "NVIDIA Corporation"
    assert result.signals[0].action == "BUY"
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "currentPrice: 100" in prompt
    assert "BUY×2" in prompt


def test_analyze_tweets_handles_no_research_without_anthropic(monkeypatch):
    client_factory = Mock()
    monkeypatch.setattr(analyzer, "_client", client_factory)
    result = analyzer.analyze_tweets("tweet", {}, {}, {"ai": {"model": "test"}})
    assert result.signals == []
    client_factory.assert_not_called()


def test_analyze_tweets_reports_truncated_response(monkeypatch):
    mocked_client(
        monkeypatch,
        claude_response('{"summary":', stop_reason="max_tokens"),
    )
    with pytest.raises(analyzer.AnalysisProviderError, match="truncated"):
        analyzer.analyze_tweets(
            "tweet",
            {"AAPL": {"price_data": {}}},
            {},
            {"ai": {"model": "test", "max_tokens": 1}},
        )


def test_analyze_tweets_rejects_invalid_signal_enums(monkeypatch):
    mocked_client(
        monkeypatch,
        claude_response(
            {
                "summary": "Invalid response",
                "signals": [
                    {
                        "ticker": "AAPL",
                        "action": "STRONG_BUY",
                        "confidence": "HIGH",
                    }
                ],
            }
        ),
    )
    with pytest.raises(analyzer.AnalysisProviderError, match="invalid action"):
        analyzer.analyze_tweets(
            "tweet",
            {"AAPL": {"price_data": {}}},
            {},
            {"ai": {"model": "test"}},
        )
