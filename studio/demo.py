"""Offline demo: `python -m studio demo [--port 8788] [--live]` seeds a throw-away studio home with the fake engine
(games, gates, player feedback, a bug fix waiting at Gate 3, agents in different states) and serves the dashboard.
It never touches your real data/ folder. Without --live the worker is off, so the screen stays still."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "reviews_com.studio.orbit_hopper_202610.csv"


def seed(home: Path):
    os.environ["STUDIO_ENGINE"] = "fake"
    os.environ["STUDIO_STANDUP_ENABLED"] = "0"
    os.environ["STUDIO_MIN_SECONDS_BETWEEN_RUNS"] = "0"
    os.environ["STUDIO_NOTIFY_DESKTOP"] = "0"
    prompts = home / "prompts"
    if not prompts.exists():
        shutil.copytree(Path(__file__).resolve().parent / "prompt_defaults", prompts)
    os.environ["STUDIO_PROMPTS"] = str(prompts)
    from . import workflow
    from .config import Paths
    from .engines import EngineResult, FakeEngine, RateLimited
    from .worker import claim_next, process_one, run_until_idle

    workflow.find_godot = lambda configured="": None
    fake = FakeEngine(agentic=True)
    st = workflow.Studio(Paths(home), fake_engine=fake)

    def pending(gate):
        return [a for a in st.db.all("SELECT * FROM approvals WHERE status='pending' ORDER BY id") if a["gate"] == gate]

    gid = st.new_game("A one-thumb space hopper for Android, 3-minute sessions", "Orbit Hopper")
    run_until_idle(st)
    st.approve(pending(1)[0]["id"])
    run_until_idle(st)
    st.approve(pending(2)[0]["id"])
    run_until_idle(st)                       # engineer ticket -> QA -> Gate 3
    st.set_game(gid, version="1.0.2")
    fb = st.feedback_dir()
    shutil.copy(FIXTURE, fb / FIXTURE.name)
    (fb / "orbit-hopper").mkdir(exist_ok=True)
    (fb / "orbit-hopper" / "support-mail-1.txt").write_text(
        "From: ana.r@example.com\nVersion: 1.0.2\n\nHi, I bought Remove Ads yesterday and I was charged twice. Can you help?")
    (fb / "orbit-hopper" / "ingame-0412.json").write_text(json.dumps({"game": "orbit-hopper", "version": "1.0.2", "items": [
        {"message": "Music stops after level 2 and never comes back", "type": "bug", "device": "Galaxy A54"},
        {"message": "Would love a dark mode and a daily challenge!", "type": "feature"},
        {"message": "free coins here telegram.me/xx idiot devs", "type": "other"}]}))
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)                       # triage, Gate 6 drafts, crash group -> Bug Fixer -> Gate 3

    fake.script("designer.pitch", "```json\n" + json.dumps({"title": "Tiny Tides", "logline": "Guide a tide pool's creatures home before the sea returns.",
                                                            "pitch_markdown": "# Tiny Tides\n\n## Hook\nDraw channels in the sand.\n\n## Monetization\nPremium unlock after 10 levels."}) + "\n```")
    st.new_game("A calm puzzle game about tide pools", "Tiny Tides")
    run_until_idle(st)

    # live-looking states
    st.set_agent("marketing", paused=True)
    st.db.set("max_attempts", "1")
    fake.script("analyst.analyze", "not json at all")
    st.add_inbox_file(gid, "revenue-oct.csv", b"day,revenue\n2026-10-01,3.20\n")
    run_until_idle(st)                       # analyst fails for good -> error state
    st.db.set("max_attempts", "5")
    st.set_agent("analyst", model="gemini-flash-latest", effort="low")
    fake.script("producer.standup", RateLimited("429 RESOURCE_EXHAUSTED: quota exceeded"))
    st.request_standup(gid)
    process_one(st, ignore_schedule=True)    # producer backs off, engine backoff shown
    st.db.update("jobs", st.db.one("SELECT id FROM jobs WHERE kind='producer.standup'")["id"], attempts=1)
    st.enqueue(gid, "artist", "ticket.work", {"note": "demo"})
    job = claim_next(st, ignore_schedule=True)   # leave one job "running" for the screenshot
    st.db.update("jobs", job["id"], started_at=job["created_at"] - 95)
    st.enqueue(gid, "qa", "qa.health", {})
    return st


def main(argv: list[str]) -> None:
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8788
    home = Path(argv[argv.index("--home") + 1]) if "--home" in argv else Path(tempfile.mkdtemp(prefix="studio-demo-"))
    st = seed(home)
    print(f"Demo studio in {home} - open http://127.0.0.1:{port}")
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(st, start_worker="--live" in argv), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main(sys.argv[1:])
