"""
emailer.py — HTML email builder and SMTP sender for the stock digest.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_ACTION_COLORS = {
    "BUY": "#1a7f1a",
    "SELL": "#c0392b",
    "HOLD": "#d68910",
    "INVESTIGATE": "#1a6fa8",
}

_ACTION_BG = {
    "BUY": "#d5f5d5",
    "SELL": "#fde0de",
    "HOLD": "#fef9e7",
    "INVESTIGATE": "#d6eaf8",
}

_CONFIDENCE_LABELS = {
    "HIGH": "●●●",
    "MEDIUM": "●●○",
    "LOW": "●○○",
}

_VIBE_COLORS = {
    "Bullish": ("#1a7f1a", "#d5f5d5"),
    "Bearish": ("#c0392b", "#fde0de"),
    "Neutral": ("#d68910", "#fef9e7"),
    "Mixed": ("#6a3fa8", "#ede0f8"),
}


def _vibe(actions: dict) -> str:
    """Derive an overall sentiment label from action counts."""
    total = sum(actions.values())
    if total == 0:
        return "Mixed"
    for label, key in [("Bullish", "BUY"), ("Bearish", "SELL"), ("Neutral", "HOLD")]:
        if actions.get(key, 0) / total > 0.5:
            return label
    return "Mixed"


def _vibe_badge(label: str) -> str:
    color, bg = _VIBE_COLORS.get(label, ("#555", "#eee"))
    return (
        f'<span style="background:{bg};color:{color};font-weight:bold;'
        f'padding:2px 8px;border-radius:4px;font-size:13px;">{label}</span>'
    )


def _weekly_section(weekly_rollup: dict) -> str:
    """Render a weekly overview card sorted by mention count."""
    if not weekly_rollup:
        return ""

    rows_html = []
    sorted_tickers = sorted(
        weekly_rollup.items(), key=lambda kv: kv[1]["total"], reverse=True
    )
    for i, (ticker, info) in enumerate(sorted_tickers):
        row_bg = "#fff" if i % 2 == 0 else "#f8f8f8"
        actions = info["actions"]
        breakdown = ", ".join(
            f'<span style="color:{_ACTION_COLORS.get(a,"#555")};font-weight:bold;">'
            f"{a}</span> ×{n}"
            for a, n in sorted(actions.items(), key=lambda kv: -kv[1])
        )
        vibe = _vibe(actions)
        rows_html.append(
            f'<tr style="background:{row_bg};border-bottom:1px solid #eee;">'
            f'<td style="padding:10px 8px;font-weight:bold;">{ticker}</td>'
            f'<td style="padding:10px 8px;text-align:center;">{info["total"]}</td>'
            f'<td style="padding:10px 8px;font-size:13px;">{breakdown}</td>'
            f'<td style="padding:10px 8px;">{_vibe_badge(vibe)}</td>'
            f'<td style="padding:10px 8px;font-size:12px;color:#888;">{info["last_seen"]}</td>'
            "</tr>"
        )

    return (
        '<div style="background:#fff;border:1px solid #ddd;border-radius:6px;'
        'padding:20px;margin-bottom:24px;">'
        '<h2 style="color:#1a1a2e;margin-top:0;">Weekly Stock Overview</h2>'
        '<table style="width:100%;border-collapse:collapse;margin-top:8px;">'
        "<thead>"
        '<tr style="background:#1a1a2e;color:#fff;">'
        '<th style="padding:10px 8px;text-align:left;">Ticker</th>'
        '<th style="padding:10px 8px;text-align:center;">Mentions</th>'
        '<th style="padding:10px 8px;text-align:left;">Signal Breakdown</th>'
        '<th style="padding:10px 8px;text-align:left;">Overall Vibe</th>'
        '<th style="padding:10px 8px;text-align:left;">Last Signal</th>'
        "</tr>"
        "</thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
        "</div>"
    )


def _signal_badge(action: str) -> str:
    color = _ACTION_COLORS.get(action, "#555")
    bg = _ACTION_BG.get(action, "#eee")
    return (
        f'<span style="background:{bg};color:{color};font-weight:bold;'
        f'padding:2px 8px;border-radius:4px;font-size:13px;">{action}</span>'
    )


def _trend_cell(ticker: str, history_summary: dict) -> str:
    info = history_summary.get(ticker)
    if not info:
        return '<span style="color:#999">—</span>'
    parts = [f"{a}×{n}" for a, n in sorted(info["actions"].items())]
    return f'<span style="font-size:12px;color:#555">{", ".join(parts)}</span>'


def build_html(
    tweet_map: dict,
    analysis,
    history_summary: dict,
    period: str = "today",
    weekly_rollup: dict | None = None,
) -> str:
    """
    Build a two-part HTML email:
      1. AI Stock Analysis (signal table + summary)
      2. Raw Tweets (collapsible section)
    """
    sections = []

    # ── Header ──────────────────────────────────────────────────────────────
    sections.append(
        '<div style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;'
        'padding:20px;background:#f9f9f9;">'
        '<h1 style="color:#222;border-bottom:3px solid #333;padding-bottom:8px;">'
        f"Twitter Stock Digest — {period}</h1>"
    )

    # ── Part 1: AI Analysis ──────────────────────────────────────────────────
    sections.append(
        '<div style="background:#fff;border:1px solid #ddd;border-radius:6px;'
        'padding:20px;margin-bottom:24px;">'
        '<h2 style="color:#1a1a2e;margin-top:0;">AI Stock Analysis</h2>'
    )

    if analysis.summary:
        sections.append(
            f'<p style="color:#444;line-height:1.6;background:#f0f4ff;'
            f'padding:12px;border-radius:4px;">{analysis.summary}</p>'
        )

    if analysis.signals:
        sections.append(
            '<table style="width:100%;border-collapse:collapse;margin-top:16px;">'
            "<thead>"
            '<tr style="background:#1a1a2e;color:#fff;">'
            '<th style="padding:10px 8px;text-align:left;">Ticker</th>'
            '<th style="padding:10px 8px;text-align:left;">Action</th>'
            '<th style="padding:10px 8px;text-align:left;">Confidence</th>'
            '<th style="padding:10px 8px;text-align:left;">Reasoning</th>'
            '<th style="padding:10px 8px;text-align:left;">30-Day Trend</th>'
            '<th style="padding:10px 8px;text-align:left;">Sources</th>'
            "</tr>"
            "</thead><tbody>"
        )
        for i, sig in enumerate(analysis.signals):
            row_bg = "#fff" if i % 2 == 0 else "#f8f8f8"
            conf_label = _CONFIDENCE_LABELS.get(sig.confidence, sig.confidence)
            conf_color = (
                "#1a7f1a"
                if sig.confidence == "HIGH"
                else "#d68910"
                if sig.confidence == "MEDIUM"
                else "#999"
            )
            source_links = " ".join(
                f'<a href="{u}" style="color:#1a6fa8;font-size:11px;">↗</a>'
                for u in (sig.source_tweets or [])
            ) or '<span style="color:#ccc">—</span>'

            sections.append(
                f'<tr style="background:{row_bg};border-bottom:1px solid #eee;">'
                f'<td style="padding:10px 8px;font-weight:bold;">{sig.ticker}</td>'
                f'<td style="padding:10px 8px;">{_signal_badge(sig.action)}</td>'
                f'<td style="padding:10px 8px;color:{conf_color};font-weight:bold;">'
                f"{conf_label}</td>"
                f'<td style="padding:10px 8px;font-size:13px;color:#333;">'
                f"{sig.reasoning}</td>"
                f'<td style="padding:10px 8px;">'
                f"{_trend_cell(sig.ticker, history_summary)}</td>"
                f'<td style="padding:10px 8px;">{source_links}</td>'
                "</tr>"
            )
        sections.append("</tbody></table>")
    else:
        sections.append(
            '<p style="color:#888;font-style:italic;">No signals generated today.</p>'
        )

    sections.append("</div>")  # close analysis card

    # ── Weekly Overview (only shown for --weekly runs) ────────────────────────
    if weekly_rollup:
        sections.append(_weekly_section(weekly_rollup))

    # ── Part 2: Raw Tweets ───────────────────────────────────────────────────
    total_tweets = sum(len(v) for v in tweet_map.values())
    sections.append(
        '<details style="margin-bottom:24px;">'
        '<summary style="cursor:pointer;font-size:16px;font-weight:bold;'
        'color:#444;padding:8px;background:#eee;border-radius:4px;">'
        f"Raw Tweets ({total_tweets} total — click to expand)</summary>"
        '<div style="margin-top:12px;">'
    )

    for username, tweets in tweet_map.items():
        if not tweets:
            continue
        sections.append(
            '<div style="background:#fff;border:1px solid #ddd;border-radius:6px;'
            'padding:16px;margin-bottom:16px;">'
            f'<h3 style="margin:0 0 12px;color:#1a1a2e;">@{username}</h3>'
        )
        for tweet in tweets:
            date_str = tweet.date.strftime("%Y-%m-%d %H:%M UTC") if hasattr(tweet, "date") and tweet.date else ""
            likes = getattr(tweet, "likeCount", 0) or 0
            rts = getattr(tweet, "retweetCount", 0) or 0
            url = getattr(tweet, "url", "") or ""
            text = getattr(tweet, "rawContent", "") or getattr(tweet, "content", "") or str(tweet)

            sections.append(
                '<div style="border-left:3px solid #ccc;padding:8px 12px;'
                'margin-bottom:10px;">'
                f'<p style="margin:0 0 6px;color:#333;font-size:14px;">{text}</p>'
                '<p style="margin:0;font-size:12px;color:#888;">'
                f'<span>{date_str}</span>'
                f'&nbsp;·&nbsp;<span>♥ {likes}</span>'
                f'&nbsp;·&nbsp;<span>↻ {rts}</span>'
            )
            if url:
                sections.append(
                    f'&nbsp;·&nbsp;<a href="{url}" style="color:#1a6fa8;">View</a>'
                )
            sections.append("</p></div>")

        sections.append("</div>")  # close user card

    sections.append("</div></details>")  # close raw tweets

    # ── Footer ───────────────────────────────────────────────────────────────
    sections.append(
        '<p style="font-size:11px;color:#aaa;text-align:center;">'
        "Generated by Twitter Stock Digest · Not financial advice</p>"
        "</div>"
    )

    return "".join(sections)


def _plain_text(analysis, tweet_map: dict) -> str:
    lines = ["Twitter Stock Digest\n", "=" * 40]
    if analysis.summary:
        lines += ["", "SUMMARY", analysis.summary]
    if analysis.signals:
        lines += ["", "SIGNALS"]
        for sig in analysis.signals:
            lines.append(
                f"  {sig.ticker}: {sig.action} ({sig.confidence}) — {sig.reasoning}"
            )
    lines += ["", "=" * 40, "Raw tweet counts:"]
    for user, tweets in tweet_map.items():
        lines.append(f"  @{user}: {len(tweets)} tweet(s)")
    return "\n".join(lines)


def send_digest(html_body: str, analysis, tweet_map: dict, config: dict) -> None:
    """Send the digest email via STARTTLS SMTP."""
    email_cfg = config["email"]
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = email_cfg["subject"]
    msg["From"] = gmail_user
    msg["To"] = email_cfg["to"]

    msg.attach(MIMEText(_plain_text(analysis, tweet_map), "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, email_cfg["to"], msg.as_string())

    logger.info("Digest email sent to %s.", email_cfg["to"])
