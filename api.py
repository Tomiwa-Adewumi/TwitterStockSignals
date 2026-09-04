"""FastAPI application exposing the Twitter Stock Signals pipeline."""

import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import yaml
from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi import (
    Path as ApiPath,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from database import (
    ActiveRunError,
    create_run,
    database_is_ready,
    get_run,
    init_database,
    list_runs,
    list_signals,
)
from schemas import AnalysisRequest, Health, Run, RunPage, Signal, SignalPage
from worker import AnalysisWorker

load_dotenv()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.0.0"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict) or not config.get("users") or not config.get("ai"):
        raise RuntimeError("Config must define non-empty 'users' and 'ai' sections")
    return config


def create_app(
    *,
    config_path: str | None = None,
    db_path: str | None = None,
    start_worker: bool = True,
) -> FastAPI:
    resolved_config_path = (
        config_path or os.environ.get("CONFIG_PATH") or str(BASE_DIR / "config.yaml")
    )
    resolved_db_path = (
        db_path or os.environ.get("DATABASE_PATH") or str(BASE_DIR / "signals.db")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = _load_config(resolved_config_path)
        app.state.db_path = resolved_db_path
        init_database(resolved_db_path)
        app.state.worker = AnalysisWorker(app.state.config, resolved_db_path)
        if start_worker:
            await app.state.worker.start()
        try:
            yield
        finally:
            if start_worker:
                await app.state.worker.stop()

    app = FastAPI(
        title="Twitter Stock Signals API",
        summary="A production HTTP interface for the Twitter stock-analysis pipeline.",
        description=(
            "Trigger X/Twitter analysis jobs and query persisted stock signals. "
            "Generated signals are informational and are not financial advice."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key"],
        )

    async def require_api_key(
        supplied_key: Annotated[str | None, Depends(api_key_header)],
    ) -> None:
        expected_key = os.getenv("API_KEY")
        allow_unauthenticated = (
            os.getenv("ALLOW_UNAUTHENTICATED_ANALYSIS", "").lower() == "true"
        )
        if not expected_key and not allow_unauthenticated:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Analysis API is disabled until API_KEY is configured",
            )
        if expected_key and (
            supplied_key is None
            or not secrets.compare_digest(supplied_key, expected_key)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key",
            )

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = (
            f"{(time.perf_counter() - started) * 1000:.2f}"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": "Twitter Stock Signals API", "docs": "/docs"}

    @app.get("/health", response_model=Health, tags=["operations"])
    async def health(request: Request, response: Response) -> Health:
        database_ready = database_is_ready(request.app.state.db_path)
        worker_state: Literal["running", "stopped", "disabled"] = (
            "running"
            if request.app.state.worker.is_running
            else "stopped"
            if start_worker
            else "disabled"
        )
        ready = database_ready and worker_state != "stopped"
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(
            status="ok" if ready else "degraded",
            database="ok" if database_ready else "unavailable",
            worker=worker_state,
            version=APP_VERSION,
        )

    @app.post(
        "/analysis",
        response_model=Run,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["analysis"],
        dependencies=[Depends(require_api_key)],
    )
    async def start_analysis(
        payload: AnalysisRequest,
        request: Request,
        response: Response,
    ) -> Run:
        period = "this week" if payload.weekly else "today"
        try:
            run_id = create_run(
                request.app.state.db_path,
                datetime.now(timezone.utc).date().isoformat(),
                period,
                ensure_idle=True,
                email_requested=payload.send_email,
            )
        except ActiveRunError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        request.app.state.worker.enqueue(run_id)
        response.headers["Location"] = f"/runs/{run_id}"
        run = get_run(request.app.state.db_path, run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Queued run could not be loaded",
            )
        return Run.model_validate(run)

    @app.get("/signals", response_model=SignalPage, tags=["signals"])
    async def get_signals(
        request: Request,
        action: Annotated[
            str | None,
            Query(pattern="^(BUY|SELL|HOLD|INVESTIGATE)$"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SignalPage:
        items, total = list_signals(
            request.app.state.db_path,
            action=action,
            limit=limit,
            offset=offset,
        )
        return SignalPage(
            items=[Signal.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get("/signals/{ticker}", response_model=SignalPage, tags=["signals"])
    async def get_ticker_signals(
        request: Request,
        ticker: Annotated[
            str,
            ApiPath(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9.-]*$"),
        ],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SignalPage:
        items, total = list_signals(
            request.app.state.db_path,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )
        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No signals found for ticker {ticker.upper()}",
            )
        return SignalPage(
            items=[Signal.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get("/runs", response_model=RunPage, tags=["analysis"])
    async def get_runs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RunPage:
        items, total = list_runs(request.app.state.db_path, limit=limit, offset=offset)
        return RunPage(
            items=[Run.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get("/runs/{run_id}", response_model=Run, tags=["analysis"])
    async def get_run_by_id(
        request: Request, run_id: Annotated[int, ApiPath(ge=1)]
    ) -> Run:
        run = get_run(request.app.state.db_path, run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
            )
        return Run.model_validate(run)

    return app


app = create_app()
