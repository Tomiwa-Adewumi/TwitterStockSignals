import io
import json
import subprocess
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.restore_state import restore


def test_restores_snapshot_without_using_git_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("signals.db", b"snapshot")
    responses = [
        SimpleNamespace(
            stdout=json.dumps({"artifacts": [{"id": 12, "expired": False}]})
        ),
        SimpleNamespace(stdout=archive.getvalue()),
    ]
    with patch("scripts.restore_state.subprocess.run", side_effect=responses) as run:
        restore()
        assert run.call_count == 2
        assert run.call_args.args[0] == [
            "gh",
            "api",
            "repos/owner/repo/actions/artifacts/12/zip",
        ]
    assert (tmp_path / "signals.db").read_bytes() == b"snapshot"


def test_expired_snapshot_fails_without_resetting_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    with (
        patch(
            "scripts.restore_state.subprocess.run",
            return_value=SimpleNamespace(
                stdout=json.dumps({"artifacts": [{"id": 12, "expired": True}]})
            ),
        ),
        pytest.raises(RuntimeError, match="expired"),
    ):
        restore()
    assert not (tmp_path / "signals.db").exists()


def test_api_failure_does_not_bootstrap_an_old_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    with (
        patch(
            "scripts.restore_state.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "gh"),
        ),
        pytest.raises(subprocess.CalledProcessError),
    ):
        restore()
    assert not (tmp_path / "signals.db").exists()
