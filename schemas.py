"""Pydantic response and request models for the HTTP API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["BUY", "SELL", "HOLD", "INVESTIGATE"]
RunStatus = Literal["queued", "running", "completed", "failed"]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekly: bool = Field(False, description="Generate the weekly roll-up.")
    send_email: bool = Field(
        False,
        description="Send the configured digest email when the analysis finishes.",
    )


class Signal(BaseModel):
    id: int
    run_id: int | None = None
    run_date: str
    ticker: str
    company_name: str = ""
    action: Action
    reasoning: str | None = None
    confidence: str | None = None
    source_tweet_urls: list[str] = Field(default_factory=list)


class SignalPage(BaseModel):
    items: list[Signal]
    total: int
    limit: int
    offset: int


class Run(BaseModel):
    id: int
    run_date: str
    summary: str | None = None
    tweet_count: int = 0
    status: RunStatus
    period: str
    email_requested: bool = False
    email_sent: bool = False
    email_error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class RunPage(BaseModel):
    items: list[Run]
    total: int
    limit: int
    offset: int


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    worker: Literal["running", "stopped", "disabled"]
    version: str
