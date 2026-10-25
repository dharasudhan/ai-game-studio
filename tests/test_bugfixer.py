"""Bug Fixer: player reports -> bug ticket with repro -> test-first fix on its own branch -> QA -> Gate 3
(never merged without approval) -> fixed items -> "fixed in vX" reply drafts at Gate 6 after release."""
import stat
from pathlib import Path

from studio import gitops
from studio.db import loads
from studio.worker import run_until_idle
from conftest import pending, released_game


def crash_reports(st, n=2):
    d = st.feedback_dir() / "orbit-hopper"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"c{i}.txt").write_text(f"From: p{i}@example.com\nVersion: 1.0.2\n\nGame crashes every time level 3 loads ({i})")
    st.enqueue(None, "support", "support.ingest", {})


def stub_godot(tmp_path: Path) -> str:
    """Pretends to be Godot: unit tests fail while a tests/test_bug_*.gd exists without its scripts/bugfix_*.gd fix."""
    p = tmp_path / "godot"
    p.write_text("""#!/bin/sh
case "$*" in
  *run_tests.gd*)
    if ls tests/test_bug_*.gd >/dev/null 2>&1 && ! ls scripts/bugfix_*.gd >/dev/null 2>&1; then
      echo "FAIL test_bug"; echo "RESULT total=3 failures=1"; exit 1
    fi
    echo "RESULT total=3 failures=0"; exit 0;;
  *) exit 0;;
esac
""")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_bugfix_loop_to_gate3_merge_and_fixed_replies(studio, fake, tmp_path, monkeypatch):
    st = studio
    godot = stub_godot(tmp_path)
    monkeypatch.setattr("studio.workflow.find_godot", lambda configured="": godot)
    gid = released_game(st)
    repo = Path(st.game(gid)["repo_path"])
    crash_reports(st, 2)
    run_until_idle(st)

    t = st.db.one("SELECT * FROM tickets WHERE kind='bug'")
    assert t["agent"] == "bugfixer" and t["branch"].startswith(f"bugfixer/t{t['id']}-")
    assert "level 3" in t["repro_steps"] and t["severity"] in ("high", "critical")
    fix_call = [c for c in fake.calls if c.task == "bugfix.fix"][0]
    assert "Player reports" in fix_call.prompt and "Game crashes every time level 3" in fix_call.prompt
    assert "test-first" in fix_call.prompt.lower() or "regression test" in fix_call.prompt

    g3 = [a for a in pending(st, 3)]
    assert len(g3) == 1
    p = loads(g3[0]["payload_json"])
    assert p["kind"] == "bug" and p["qa_passed"] is True and p["regression_test"] == f"tests/test_bug_t{t['id']}.gd"
    assert sorted(p["feedback_items"]) == sorted(r["id"] for r in st.db.all("SELECT id FROM feedback_items"))
    assert "PASS bug fix has a regression test" in p["qa_markdown"]
    assert "PASS regression test fails on main (reproduces the bug)" in p["qa_markdown"]
    # never merged without approval
    assert not (repo / f"scripts/bugfix_t{t['id']}.gd").exists()
    assert st.ticket(t["id"])["status"] == "awaiting_approval"

    st.approve(g3[0]["id"])
    assert (repo / f"scripts/bugfix_t{t['id']}.gd").exists()
    assert "Merge T#" in gitops.git(repo, "log", "-1", "--pretty=%s")
    rows = st.db.all("SELECT * FROM feedback_items")
    assert all(r["fixed_sha"] for r in rows)

    # owner marks the version and asks Support for follow-ups (also happens automatically on Gate 5)
    st.set_game(gid, version="1.0.3")
    assert st.queue_fixed_replies(gid, "1.0.3")
    run_until_idle(st)
    replies = [a for a in pending(st, 6) if a["kind"] == "reply"]
    follow = [a for a in replies if loads(a["payload_json"])["followup"]]
    assert len(follow) == 2 == len(replies), "the follow-up replaces the first draft still waiting (one reply per player)"
    assert "v1.0.3" in loads(follow[0]["payload_json"])["content"] and "fixed in 1.0.3" in follow[0]["title"]
    assert all(r["fixed_in_version"] == "1.0.3" for r in st.db.all("SELECT * FROM feedback_items"))
    assert st.queue_fixed_replies(gid, "1.0.3") is None  # nothing left to follow up


def test_fix_without_regression_test_bounces_back(studio, fake, tmp_path, monkeypatch):
    st = studio
    godot = stub_godot(tmp_path)
    monkeypatch.setattr("studio.workflow.find_godot", lambda configured="": godot)
    released_game(st)

    def no_test(req):
        p = Path(req.cwd) / "scripts" / "bugfix_quick.gd"
        p.parent.mkdir(exist_ok=True)
        p.write_text("extends RefCounted\n")
        return '```json\n{"summary":"quick fix","regression_test":"","no_test_reason":""}\n```'
    fake.script("bugfix.fix", no_test)
    crash_reports(st, 1)
    run_until_idle(st)
    fixes = [c for c in fake.calls if c.task == "bugfix.fix"]
    assert len(fixes) == 2, "QA sent the fix back for a missing regression test"
    assert "FAIL bug fix has a regression test" in fixes[1].prompt
    assert len(pending(st, 3)) == 1
    assert st.db.one("SELECT qa_loops FROM tickets WHERE kind='bug'")["qa_loops"] == 1


def test_owner_flag_and_threshold(studio, fake):
    st = studio
    gid = released_game(st)
    st.db.set("bugfix_min_severity", "critical")
    d = st.feedback_dir()
    (d / "a.txt").write_text("Game: orbit-hopper\n\nthe pause button is a bit broken")  # bug, med -> below threshold
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    assert st.db.one("SELECT COUNT(*) n FROM tickets WHERE kind='bug'")["n"] == 0
    it = st.db.one("SELECT * FROM feedback_items")
    st.flag_bug(it["id"])  # owner decides it matters anyway
    run_until_idle(st)
    assert st.db.one("SELECT COUNT(*) n FROM tickets WHERE kind='bug'")["n"] == 1
    assert st.db.one("SELECT owner_flag FROM feedback_items")["owner_flag"] == 1
    assert len(pending(st, 3)) == 1


def test_bug_reports_wait_for_repo(studio):
    st = studio
    gid = st.new_game("tiny game")
    run_until_idle(st)  # concept pitched, Gate 1 pending, no repo yet
    st.set_game(gid, slug="tiny")
    (st.feedback_dir() / "x.txt").write_text("Game: tiny\n\ncrashes on start every time")
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    assert st.db.one("SELECT COUNT(*) n FROM jobs WHERE kind='bugfix.intake'")["n"] == 0
    assert any("no repo yet" in e["message"] for e in st.db.all("SELECT message FROM events"))


def test_standup_includes_feedback(studio, fake):
    st = studio
    gid = released_game(st)
    crash_reports(st, 1)
    run_until_idle(st)
    st.request_standup(gid)
    run_until_idle(st)
    call = [c for c in fake.calls if c.task == "producer.standup"][-1]
    assert "Player feedback (last 24 h): 1 crash" in call.prompt and "Open bug tickets from players" in call.prompt
