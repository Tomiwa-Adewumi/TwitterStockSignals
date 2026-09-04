from email import message_from_string
from unittest.mock import Mock

import emailer
from analyzer import AnalysisResult, StockSignal
from scraper import Tweet


def sample_analysis():
    return AnalysisResult(
        summary="Technology shares were constructive.",
        signals=[
            StockSignal(
                ticker="AAPL",
                company_name="Apple Inc.",
                action="BUY",
                confidence="HIGH",
                reasoning="Demand remains healthy.",
                source_tweets=["https://x.com/analyst/status/1"],
            )
        ],
    )


def test_build_html_renders_analysis_history_and_weekly_rollup():
    history = {
        "AAPL": {
            "total": 3,
            "actions": {"BUY": 2, "HOLD": 1},
            "last_seen": "2026-09-03",
        }
    }
    html = emailer.build_html(
        {"analyst": [Tweet("AAPL tweet", None, "https://x.com/a/1")]},
        sample_analysis(),
        history,
        period="this week",
        weekly_rollup=history,
    )
    assert "Technology shares were constructive." in html
    assert "Apple Inc." in html
    assert "Weekly Stock Overview" in html
    assert "BUY×2" in html
    assert "Raw Tweets (1 total" in html


def test_send_digest_uses_starttls_and_configured_recipient(monkeypatch):
    smtp = Mock()
    smtp.__enter__ = Mock(return_value=smtp)
    smtp.__exit__ = Mock(return_value=False)
    smtp_factory = Mock(return_value=smtp)
    monkeypatch.setattr(emailer.smtplib, "SMTP", smtp_factory)
    monkeypatch.setenv("GMAIL_USER", "sender@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    config = {
        "email": {
            "subject": "Signals",
            "to": "recipient@example.com",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
        }
    }

    emailer.send_digest("<p>digest</p>", sample_analysis(), {"analyst": []}, config)

    smtp_factory.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("sender@example.com", "secret")
    args = smtp.sendmail.call_args.args
    assert args[:2] == ("sender@example.com", "recipient@example.com")
    message = message_from_string(args[2])
    assert message["Subject"] == "Signals"
    assert message["To"] == "recipient@example.com"


def test_build_html_escapes_untrusted_content_and_rejects_unsafe_urls():
    analysis = AnalysisResult(
        summary="<script>alert('summary')</script>",
        signals=[
            StockSignal(
                ticker="AAPL",
                company_name="<b>Apple</b>",
                action="BUY",
                confidence="HIGH",
                reasoning="<img src=x onerror=alert(1)>",
                source_tweets=["javascript:alert(1)"],
            )
        ],
    )
    html = emailer.build_html(
        {
            "bad<script>": [
                Tweet(
                    "<script>alert('tweet')</script>",
                    None,
                    "javascript:alert(1)",
                )
            ]
        },
        analysis,
        {},
    )

    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "javascript:" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;Apple&lt;/b&gt;" in html
