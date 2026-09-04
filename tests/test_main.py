import asyncio
from unittest.mock import AsyncMock

import pytest
import yaml

import main
from pipeline import PipelineResult


def test_load_config_validates_required_sections(tmp_path):
    valid = tmp_path / "valid.yaml"
    valid.write_text(
        yaml.safe_dump({"users": ["analyst"], "ai": {"model": "test"}}),
        encoding="utf-8",
    )
    assert main.load_config(str(valid))["users"] == ["analyst"]

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump({"users": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="users.*ai"):
        main.load_config(str(invalid))


def test_cli_wrapper_uses_shared_pipeline_and_prints_dry_run(
    tmp_path, monkeypatch, capsys
):
    db_path = str(tmp_path / "signals.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    execute = AsyncMock(
        return_value=PipelineResult(
            run_id=1,
            status="completed",
            summary="summary",
            tweet_count=1,
            signal_count=1,
            email_sent=False,
            html="<html>digest</html>",
        )
    )
    monkeypatch.setattr(main, "execute_pipeline", execute)
    config = {"users": ["analyst"], "ai": {"model": "test"}}

    asyncio.run(main.run(config, "today", dry_run=True, weekly=True))

    execute.assert_awaited_once_with(
        config,
        db_path,
        period="this week",
        send_email=False,
    )
    assert capsys.readouterr().out.strip() == "<html>digest</html>"
