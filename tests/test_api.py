import pytest
import yaml
from fastapi.testclient import TestClient

import api
from analyzer import StockSignal
from database import save_signals


@pytest.fixture(autouse=True)
def configured_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")


def make_client(tmp_path, *, authenticated=True, start_worker=False):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"users": ["example"], "ai": {"model": "test"}}),
        encoding="utf-8",
    )
    db_path = str(tmp_path / "signals.db")
    headers = {"X-API-Key": "test-key"} if authenticated else {}
    return (
        TestClient(
            api.create_app(
                config_path=str(config_path),
                db_path=db_path,
                start_worker=start_worker,
            ),
            headers=headers,
        ),
        db_path,
    )


def test_health_and_openapi(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        assert client.get("/health").json()["status"] == "ok"
        schema = client.get("/openapi.json").json()
        assert "/analysis" in schema["paths"]
        assert "/signals/{ticker}" in schema["paths"]
        assert "APIKeyHeader" in schema["components"]["securitySchemes"]


def test_signal_and_run_endpoints(tmp_path):
    client, db_path = make_client(tmp_path)
    with client:
        save_signals(
            db_path,
            "2026-09-03",
            [
                StockSignal(
                    ticker="AAPL",
                    company_name="Apple Inc.",
                    action="HOLD",
                    confidence="MEDIUM",
                    reasoning="Mixed signals.",
                    source_tweets=[],
                )
            ],
            "Mixed session.",
            4,
        )
        response = client.get("/signals/AAPL")
        assert response.status_code == 200
        assert response.json()["items"][0]["ticker"] == "AAPL"
        assert client.get("/signals/MSFT").status_code == 404
        assert client.get("/runs").json()["total"] == 1
        run_id = client.get("/runs").json()["items"][0]["id"]
        assert client.get(f"/runs/{run_id}").json()["summary"] == "Mixed session."


def test_analysis_is_queued(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = client.post("/analysis", json={})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.headers["location"].startswith("/runs/")


def test_analysis_rejects_concurrent_run(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        assert client.post("/analysis", json={}).status_code == 202
        response = client.post("/analysis", json={})
    assert response.status_code == 409


def test_analysis_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret")
    client, _ = make_client(tmp_path, authenticated=False)
    with client:
        assert client.post("/analysis", json={}).status_code == 401
        response = client.post(
            "/analysis", json={}, headers={"X-API-Key": "test-secret"}
        )
    assert response.status_code == 202


def test_analysis_is_disabled_without_security_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_ANALYSIS", raising=False)
    client, _ = make_client(tmp_path, authenticated=False)
    with client:
        response = client.post("/analysis", json={})
    assert response.status_code == 503
    assert "API_KEY" in response.json()["detail"]


def test_analysis_passes_weekly_and_email_options_to_worker(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = client.post("/analysis", json={"weekly": True, "send_email": True})
    assert response.status_code == 202
    assert response.json()["period"] == "this week"
    assert response.json()["email_requested"] is True


def test_request_validation_and_missing_resources(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        assert client.get("/signals?limit=0").status_code == 422
        assert client.get("/signals?action=buy").status_code == 422
        assert client.get("/signals/not%20valid").status_code == 422
        assert client.get("/runs/999").status_code == 404
        assert client.post("/analysis", json={"unexpected": True}).status_code == 422


def test_pagination_and_action_filter(tmp_path):
    client, db_path = make_client(tmp_path)
    with client:
        save_signals(
            db_path,
            "2026-09-03",
            [
                StockSignal("AAPL", "Apple", "BUY", "HIGH", "Strong", []),
                StockSignal("NVDA", "NVIDIA", "HOLD", "LOW", "Mixed", []),
            ],
            "summary",
            2,
        )
        response = client.get("/signals?action=BUY&limit=1&offset=0")
        body = response.json()
        assert response.status_code == 200
        assert body["total"] == 1
        assert body["limit"] == 1
        assert body["items"][0]["ticker"] == "AAPL"


def test_health_returns_503_when_database_is_unavailable(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    monkeypatch.setattr(api, "database_is_ready", lambda _path: False)
    with client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_request_metadata_headers_and_root(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = client.get("/", headers={"X-Request-ID": "request-123"})
    assert response.json()["docs"] == "/docs"
    assert response.headers["x-request-id"] == "request-123"
    assert float(response.headers["x-process-time-ms"]) >= 0
