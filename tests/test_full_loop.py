"""End-to-end: new game -> pitch -> Gate1 -> plan -> Gate2 -> ticket -> engineer -> QA -> Gate3 -> merge -> release."""
from pathlib import Path

import pytest

from studio import gitops
from studio.worker import run_until_idle
from conftest import pending


def test_full_loop(studio, fake):
    st = studio
    gid = st.new_game("A one-thumb space hopper for Android", "Hopper")
    run_until_idle(st)

    # Gate 1: concept pitch waits; no repo exists until approval
    g1 = pending(st, 1)
    assert len(g1) == 1 and g1[0]["kind"] == "concept"
    assert st.game(gid)["repo_path"] == ""
    assert st.game(gid)["status"] == "concept_review"

    # Reject with a note -> note is fed back into the designer's next prompt
    st.reject(g1[0]["id"], "Make it calmer, no timers")
    run_until_idle(st)
    pitch_calls = [c for c in fake.calls if c.task == "designer.pitch"]
    assert len(pitch_calls) == 2 and "Make it calmer, no timers" in pitch_calls[-1].prompt
    g1 = pending(st, 1)
    assert len(g1) == 1

    st.approve(g1[0]["id"])
    g = st.game(gid)
    repo = Path(g["repo_path"])
    assert (repo / "project.godot").exists() and (repo / ".git").exists()
    assert g["slug"] == "orbit-hopper" and g["status"] == "planning"

    # Gate 2: milestone plan
    run_until_idle(st)
    g2 = pending(st, 2)
    assert len(g2) == 1
    assert st.db.all("SELECT * FROM tickets") == []  # nothing materialised before approval
    st.approve(g2[0]["id"])
    tickets = st.db.all("SELECT * FROM tickets")
    assert len(tickets) == 1 and tickets[0]["agent"] == "engineer"
    tid = tickets[0]["id"]

    # Engineer works on a branch, QA verifies, Gate 3 waits
    run_until_idle(st)
    g3 = pending(st, 3)
    assert len(g3) == 1
    t = st.ticket(tid)
    assert t["status"] == "awaiting_approval"
    feature = f"scripts/feature_t{tid}.gd"
    assert not (repo / feature).exists(), "main must not change before Gate 3"
    assert t["branch"] in gitops.git(repo, "branch")
    from studio.db import loads
    payload = loads(g3[0]["payload_json"])
    assert feature in payload["files"] and "+func value() -> int:" in payload["diff"]
    assert payload["qa_passed"] is True

    st.approve(g3[0]["id"])
    assert (repo / feature).exists()
    assert st.ticket(tid)["status"] == "done"
    assert "Merge T#" in gitops.git(repo, "log", "-1", "--pretty=%s")
    assert not Path(t["worktree"]).exists()

    # Milestone complete -> release prep -> Gate 5 store release + Gate 6 public post
    run_until_idle(st)
    assert st.game(gid)["status"] == "release_review"
    assert len(pending(st, 5)) == 1 and len(pending(st, 6)) == 1
    kinds = {d["kind"] for d in st.db.all("SELECT kind FROM docs")}
    assert {"store_listing", "screenshots_plan", "trailer_script", "release_qa", "qa_report"} <= kinds

    # Reject the public post -> marketing redrafts -> approve the redraft
    st.reject(pending(st, 6)[0]["id"], "Less hype")
    run_until_idle(st)
    g6 = pending(st, 6)
    assert len(g6) == 1 and "launches this week" in loads(g6[0]["payload_json"])["content"]
    st.approve(g6[0]["id"])

    st.approve(pending(st, 5)[0]["id"])
    assert st.game(gid)["status"] == "released"
    assert pending(st) == []
    assert st.db.one("SELECT COUNT(*) n FROM jobs WHERE status<>'done'")["n"] == 0


def test_qa_failure_bounces_back_then_passes(studio, fake):
    st = studio
    fake.script("qa.review", '```json\n{"verdict":"fail","summary":"no edge case","bugs":[{"title":"Hop at zero speed","severity":"med","details":"divide by zero"}]}\n```')
    gid = st.new_game("puzzle game")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st); st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    work = [c for c in fake.calls if c.task == "ticket.work"]
    assert len(work) == 2
    assert "Hop at zero speed" in work[1].prompt
    t = st.db.one("SELECT * FROM tickets")
    assert t["qa_loops"] == 1 and t["status"] == "awaiting_approval"
    assert len(pending(st, 3)) == 1


def test_reject_change_feeds_note_back(studio, fake):
    st = studio
    st.new_game("idle game")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st); st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    st.reject(pending(st, 3)[0]["id"], "Use signals instead of polling")
    run_until_idle(st)
    work = [c for c in fake.calls if c.task == "ticket.work"]
    assert "Use signals instead of polling" in work[-1].prompt
    assert len(pending(st, 3)) == 1
    with pytest.raises(ValueError):
        st.reject(pending(st, 3)[0]["id"], "")  # note is mandatory


def test_spend_needs_gate4(studio, fake):
    st = studio
    fake.script("ticket.work", lambda req: (Path(req.cwd, "scripts").mkdir(exist_ok=True),
                                            Path(req.cwd, "scripts/sfx.gd").write_text("extends Node\n"),
                                            '```json\n{"summary":"sfx hook","spend_requests":[{"amount":12.5,"currency":"EUR","vendor":"SoundPack","reason":"jump sfx"}]}\n```')[-1])
    st.new_game("runner")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st); st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    g4 = pending(st, 4)
    assert len(g4) == 1
    led = st.db.one("SELECT * FROM ledger")
    assert led["status"] == "proposed" and led["amount"] == 12.5
    with pytest.raises(ValueError):
        st.mark_spent(led["id"])
    st.approve(g4[0]["id"])
    st.mark_spent(led["id"])
    assert st.db.one("SELECT status FROM ledger")["status"] == "spent"


def test_non_agentic_engine_returns_files(studio, fake):
    fake.agentic = False
    st = studio
    st.new_game("match-3")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st); st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    assert len(pending(st, 3)) == 1
    st.approve(pending(st, 3)[0]["id"])
    repo = Path(st.db.one("SELECT repo_path FROM games")["repo_path"])
    assert list((repo / "scripts").glob("feature_t*.gd"))


def test_path_traversal_is_refused(studio, fake):
    st = studio
    st.db.set("max_attempts", "2")
    for _ in range(2):
        fake.script("ticket.work", '```json\n{"summary":"x","files":[{"path":"../../evil.txt","content":"x"}]}\n```')
    st.new_game("arcade")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st); st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    job = st.db.one("SELECT * FROM jobs WHERE kind='ticket.work'")
    assert job["status"] == "failed" and "outside the project" in job["last_error"]
    assert st.db.one("SELECT status FROM tickets")["status"] == "needs_attention"
    assert not (st.paths.home / "evil.txt").exists()


def test_analyst_inbox_proposes_followup_plan(studio, fake):
    st = studio
    gid = st.new_game("tower defense")
    run_until_idle(st); st.approve(pending(st, 1)[0]["id"])
    st.add_inbox_file(gid, "reviews.csv", b"rating,text\n1,crashes on level 3\n5,love it\n")
    run_until_idle(st)
    assert any("crashes on level 3" in c.prompt for c in fake.calls if c.task == "analyst.analyze")
    plans = pending(st, 2)
    follow = [p for p in plans if "Follow-up" in p["title"]]
    assert len(follow) == 1
    assert st.db.one("SELECT COUNT(*) n FROM docs WHERE kind='analysis'")["n"] == 1


def test_double_approval_refused(studio):
    st = studio
    st.new_game("x")
    run_until_idle(st)
    a = pending(st, 1)[0]
    st.approve(a["id"])
    with pytest.raises(ValueError):
        st.approve(a["id"])
