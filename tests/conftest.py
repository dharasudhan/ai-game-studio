import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio.config import Paths  # noqa: E402
from studio.engines import FakeEngine  # noqa: E402
from studio.workflow import Studio  # noqa: E402


@pytest.fixture
def fake():
    return FakeEngine(agentic=True)


@pytest.fixture
def studio(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("STUDIO_ENGINE", "fake")
    monkeypatch.setenv("STUDIO_STANDUP_ENABLED", "0")
    monkeypatch.setenv("STUDIO_GODOT_BIN", os.environ.get("GODOT_BIN", ""))
    monkeypatch.setenv("STUDIO_NOTIFY_DESKTOP", "0")
    # prompts are editable from the dashboard: tests work on a copy, never on the repo's prompts/
    prompts = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", prompts)
    monkeypatch.setenv("STUDIO_PROMPTS", str(prompts))
    for k in ("STUDIO_IMAP_HOST", "STUDIO_IMAP_USER", "STUDIO_IMAP_PASSWORD", "STUDIO_NOTIFY_WEBHOOK",
              "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    # never touch the real Keychain or the real .env; never fetch the network from an audit
    monkeypatch.setenv("STUDIO_NO_KEYCHAIN", "1")
    monkeypatch.setenv("STUDIO_ENV_FILE", str(tmp_path / "test.env"))
    monkeypatch.setenv("STUDIO_AUDIT_FETCH_PRIVACY_POLICY", "0")
    st = Studio(Paths(tmp_path / "home"), fake_engine=fake)
    if not os.environ.get("GODOT_BIN"):
        # make sure a stray godot on PATH doesn't change results; real-engine runs set GODOT_BIN
        monkeypatch.setattr("studio.workflow.find_godot", lambda configured="": None)
    return st


def pending(st, gate=None):
    rows = st.db.all("SELECT * FROM approvals WHERE status='pending' ORDER BY id")
    return [r for r in rows if gate is None or r["gate"] == gate]


def released_game(st, title_goal="cozy ferry puzzle"):
    """Fast-forward a game to having a repo and an approved plan (milestone tickets done or not)."""
    from studio.worker import run_until_idle
    gid = st.new_game(title_goal)
    run_until_idle(st)
    st.approve(pending(st, 1)[0]["id"])
    return gid
