"""Restore the newest workflow snapshot; never silently reset expired history."""

import json
import os
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path


def restore():
    repository = os.environ["GITHUB_REPOSITORY"]
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repository}/actions/artifacts?name=digest-state&per_page=1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    artifacts = json.loads(result.stdout)["artifacts"]
    if artifacts:
        artifact = artifacts[0]
        if artifact["expired"]:
            raise RuntimeError(
                "Latest digest-state artifact expired; restore a backup before continuing"
            )
        # gh follows GitHub's authenticated redirect without exposing a token in logs.
        archive = subprocess.run(
            ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact['id']}/zip"],
            capture_output=True,
            check=True,
        ).stdout
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            Path("signals.db").write_bytes(bundle.read("signals.db"))
    else:
        # One-time migration seed remains recoverable from Git history.
        data = subprocess.run(
            ["git", "show", "3962f781d49d8613d1042e1a33a526d56848a83c:signals.db"],
            capture_output=True,
            check=True,
        ).stdout
        Path("signals.db").write_bytes(data)


if __name__ == "__main__":
    restore()
