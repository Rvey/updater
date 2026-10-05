import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app import main

APP_SCRIPT = Path(main.__file__).with_name("connect.sh")
REPO_SCRIPT = Path(__file__).resolve().parents[2] / "commands" / "install.sh"


def _run(script_text: str, args: list[str], home: Path, extra_path: Path | None = None):
    env = {
        "HOME": str(home),
        "PATH": f"{extra_path}:{os.environ['PATH']}" if extra_path else os.environ["PATH"],
        "UPDATER_CONNECT_NO_TTY": "1",
    }
    return subprocess.run(
        ["bash", "-s", "--", *args],
        input=script_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_served_script_matches_repo_copy_and_parses() -> None:
    assert APP_SCRIPT.read_text() == REPO_SCRIPT.read_text(), "run: cp commands/install.sh backend/app/connect.sh"
    assert subprocess.run(["bash", "-n", str(APP_SCRIPT)]).returncode == 0
    res = TestClient(main.app).get("/connect.sh")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"


def test_truncated_download_installs_nothing(tmp_path) -> None:
    text = APP_SCRIPT.read_text()
    res = _run(text[: len(text) // 2], ["--url", "http://x/mcp", "-y"], tmp_path)
    assert res.returncode != 0
    assert not (tmp_path / ".claude").exists()


def test_token_is_never_executed_or_logged(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    fake = bin_dir / "claude"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    fake.chmod(0o755)
    marker = tmp_path / "PWNED"
    token = f'se"cret$(touch {marker})zz'
    res = _run(
        APP_SCRIPT.read_text(),
        ["--url", "http://x/mcp", "--agents", "claude", "--token", token, "--skip-token-check", "-y"],
        tmp_path / "home",
        bin_dir,
    )
    assert res.returncode == 0, res.stderr
    assert not marker.exists()
    assert token not in res.stdout + res.stderr
    assert token in calls.read_text()  # passed verbatim to the CLI
    assert (tmp_path / "home/.claude/commands/updater.md").exists()


def test_invalid_cursor_config_is_preserved_and_fails(tmp_path) -> None:
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir()
    cfg.write_text("{not json")
    res = _run(APP_SCRIPT.read_text(), ["--url", "http://x/mcp", "--agents", "cursor", "--skip-token-check", "-y"], tmp_path)
    assert res.returncode != 0
    assert cfg.read_text() == "{not json"
