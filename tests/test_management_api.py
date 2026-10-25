"""Management UI backing API: status, agents (enable/pause/engine/model/effort/run-now/prompts/feedback memory),
settings (validation, secrets never shown), feedback inbox endpoints; worker limits; notifications."""
import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from studio import notify as nt
from studio.app import create_app
from studio.engines import GenAIEngine, RateLimited
from studio.worker import claim_next, process_one, run_until_idle, standup_due
from conftest import pending, released_game

H = {"X-Studio": "1"}
FIX = Path(__file__).parent / "fixtures"


def client(st):
    return TestClient(create_app(st, start_worker=False))


def test_ui_pages_served(studio):
    c = client(studio)
    html = c.get("/").text
    for word in ("Approval Desk", 'data-tab="status"', 'data-tab="agents"', 'data-tab="feedback"', 'data-tab="settings"', "/static/app.js"):
        assert word in html
    assert c.get("/static/app.js").status_code == 200 and c.get("/static/app.css").status_code == 200


def test_status_lists_every_agent_with_state(studio, fake):
    st = studio
    c = client(st)
    st.new_game("space hopper")
    s = c.get("/api/status").json()
    names = [a["name"] for a in s["agents"]]
    assert names == ["producer", "designer", "engineer", "artist", "qa", "marketing", "analyst", "support", "bugfixer"]
    d = next(a for a in s["agents"] if a["name"] == "designer")
    assert d["state"] == "queued" and d["queue_length"] == 1 and d["label"] == "Game Designer"
    run_until_idle(st)
    s = c.get("/api/status").json()
    d = next(a for a in s["agents"] if a["name"] == "designer")
    assert d["state"] == "idle" and d["last_result"]["status"] == "ok" and d["last_result"]["summary"] == "Orbit Hopper"
    assert d["recent_runs"] and c.get(f"/api/runs/{d['last_result']['run_id']}").json()["output"]
    assert s["approvals_waiting"] == {"1": 1} and s["approvals_total"] == 1
    assert s["secrets"]["STUDIO_IMAP_PASSWORD"] == "not set"
    # error state after a job fails for good
    st.db.set("max_attempts", "1")
    fake.script("designer.pitch", "garbage")
    st.reject(pending(st, 1)[0]["id"], "again")
    run_until_idle(st)
    d = next(a for a in c.get("/api/status").json()["agents"] if a["name"] == "designer")
    assert d["state"] == "error" and d["last_error"]


def test_agent_pause_disable_and_engine_override(studio, fake):
    st = studio
    c = client(st)
    assert c.post("/api/agents/designer", json={"paused": True}, headers=H).json()["paused"] == 1
    st.new_game("x")
    assert process_one(st, ignore_schedule=True) is False, "paused agent's job is not claimed"
    assert next(a for a in c.get("/api/status").json()["agents"] if a["name"] == "designer")["state"] == "paused"
    c.post("/api/agents/designer", json={"paused": False}, headers=H)
    assert claim_next(st, ignore_schedule=True)["kind"] == "designer.pitch"
    r = c.post("/api/agents/marketing", json={"engine": "genai", "model": "gemini-2.5-pro", "effort": "high"}, headers=H).json()
    assert r["engine"] == "genai" and r["model"] == "gemini-2.5-pro"
    e = st.engine_for("marketing", "marketing.release_kit")
    assert isinstance(e, GenAIEngine) and e.model == "gemini-2.5-pro"
    c.post("/api/agents/qa", json={"engine": "agy", "model": "gemini-3-flash", "effort": "low"}, headers=H)
    e = st.engine_for("qa", "qa.review")
    assert e.name == "agy" and e.model == "gemini-3-flash" and e.effort == "low"
    assert c.post("/api/agents/qa", json={"engine": "gpt"}, headers=H).status_code == 400
    assert c.post("/api/agents/qa", json={"model": "x; rm -rf /"}, headers=H).status_code == 400
    assert c.post("/api/agents/nobody", json={"paused": True}, headers=H).status_code == 404
    assert c.post("/api/agents/qa", json={"enabled": False}, headers=H).json()["enabled"] == 0
    assert c.post("/api/agents/qa/run", json={"game_id": None}, headers=H).status_code == 400  # disabled
    c.post("/api/agents-all/pause", headers=H)
    assert all(a["paused"] for a in c.get("/api/agents").json()["agents"])


def test_run_now(studio, fake):
    st = studio
    c = client(st)
    gid = released_game(st)
    assert c.post("/api/agents/designer/run", json={"game_id": gid}, headers=H).status_code == 400  # not at concept stage
    jid = c.post("/api/agents/producer/run", json={"game_id": gid}, headers=H).json()["job_id"]
    assert st.db.one("SELECT next_run_at FROM jobs WHERE id=?", jid)["next_run_at"] == 0  # jumps the queue
    assert claim_next(st, ignore_schedule=True)["id"] == jid
    st.db.update("jobs", jid, status="queued")  # hand it back to the normal drain
    assert c.post("/api/agents/qa/run", json={"game_id": gid}, headers=H).status_code == 200
    assert c.post("/api/agents/support/run", json={}, headers=H).status_code == 200
    assert c.post("/api/agents/analyst/run", json={"game_id": gid}, headers=H).status_code == 400  # empty inbox
    assert c.post("/api/agents/engineer/run", json={"game_id": gid}, headers=H).status_code == 400  # no tickets yet
    run_until_idle(st)
    assert st.db.one("SELECT COUNT(*) n FROM docs WHERE kind='qa_report' AND title LIKE 'QA health%'")["n"] == 1


def test_prompt_edit_and_reset(studio):
    st = studio
    c = client(st)
    p = c.get("/api/agents/support/prompt").json()
    assert "Customer Support" in p["content"] and p["customized"] is False
    r = c.post("/api/agents/support/prompt", json={"content": "# Role: Support\nBe brief."}, headers=H).json()
    assert r["customized"] is True and Path(r["path"]).read_text().startswith("# Role: Support")
    assert Path(r["path"]).parent == st.paths.prompts  # the test copy, not the repo
    assert c.post("/api/agents/support/prompt", json={"content": " "}, headers=H).status_code == 400
    assert c.post("/api/agents/support/prompt/reset", headers=H).json()["customized"] is False
    assert c.get("/api/agents/_common/prompt").status_code == 200
    assert c.get("/api/agents/../etc/prompt").status_code == 404
    assert c.get("/api/agents/hacker/prompt").status_code == 404


def test_feedback_memory_view_and_delete(studio):
    st = studio
    c = client(st)
    st.new_game("x")
    run_until_idle(st)
    st.reject(pending(st, 1)[0]["id"], "No timers please")
    notes = c.get("/api/agents/designer/feedback").json()["notes"]
    assert notes[0]["note"] == "No timers please" and notes[0]["gate"] == 1
    assert c.delete(f"/api/agent-feedback/{notes[0]['id']}", headers=H).json()["ok"]
    assert c.get("/api/agents/designer/feedback").json()["notes"] == []


def test_settings_schema_validation_and_secrets(studio, monkeypatch):
    c = client(studio)
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    s = c.get("/api/settings").json()
    assert s["secrets"]["GEMINI_API_KEY"] == "set" and s["secrets"]["STUDIO_IMAP_PASSWORD"] == "not set"
    assert "super-secret-value" not in json.dumps(s) and "super-secret-value" not in c.get("/api/status").text
    assert "super-secret-value" not in c.get("/api/state").text
    assert s["schema"]["standup_time"]["group"] == "Schedule" and "feedback_imap_enabled" in s["values"]
    ok = {"standup_time": "08:15", "work_hours": "08:00-23:00", "concurrency": "2", "feedback_game_map": '{"com.x":"x"}',
          "notify_desktop": "off", "engine": "genai", "monthly_budget": "50"}
    r = c.post("/api/settings", json=ok, headers=H).json()
    assert r["standup_time"] == "08:15" and r["concurrency"] == "2" and r["notify_desktop"] == "0"
    for bad in ({"standup_time": "25:00"}, {"work_hours": "8-23"}, {"concurrency": "9"}, {"feedback_game_map": "[1]"},
                {"engine": "gpt5"}, {"max_attempts": "-1"}, {"paused": "0"}, {"GEMINI_API_KEY": "x"}):
        assert c.post("/api/settings", json=bad, headers=H).status_code == 400, bad


def test_feedback_api_upload_filter_edit_flag(studio, fake):
    st = studio
    c = client(st)
    gid = released_game(st)
    r = c.post("/api/feedback/upload", files={"file": (FIX.joinpath("reviews_com.ottranstudios.orbit_hopper_202610.csv").name,
                                                         FIX.joinpath("reviews_com.ottranstudios.orbit_hopper_202610.csv").read_bytes())}, headers=H)
    assert r.status_code == 200
    assert c.post("/api/feedback/upload", files={"file": ("x.exe", b"x")}, headers=H).status_code == 400
    assert c.post("/api/feedback/ingame", json={"game": "orbit-hopper", "message": "pls add dark mode"}, headers=H).status_code == 200
    run_until_idle(st)
    allf = c.get("/api/feedback").json()
    assert allf["counts"]["total"] == 5 and allf["groups"] and "play" in allf["counts"]["source"]
    crash = c.get("/api/feedback", params={"category": "crash"}).json()["items"]
    assert len(crash) == 2 and all(i["game_title"] == "Orbit Hopper" for i in crash)
    assert c.get("/api/feedback", params={"q": "dark mode"}).json()["items"][0]["source"] == "ingame"
    assert len(c.get("/api/feedback", params={"bug": "linked"}).json()["items"]) == 2
    item = c.get("/api/feedback", params={"category": "feature_request", "source": "play"}).json()["items"][0]
    e = c.post(f"/api/feedback/{item['id']}/draft", json={"text": "Thank you! More levels soon."}, headers=H).json()
    assert e["reply_draft"] == "Thank you! More levels soon."
    assert c.post(f"/api/feedback/{item['id']}/status", json={"status": "bogus"}, headers=H).status_code == 400
    assert c.post(f"/api/feedback/{item['id']}/status", json={"status": "ignored"}, headers=H).json()["status"] == "ignored"
    assert c.post(f"/api/feedback/{item['id']}/flag_bug", headers=H).status_code == 200
    assert c.get(f"/api/feedback/{item['id']}").json()["owner_flag"] == 1
    bugs = c.get("/api/bugs").json()["bugs"]
    assert bugs and bugs[0]["feedback_items"]
    assert c.post(f"/api/games/{gid}/version", json={"version": "1.0.3"}, headers=H).json()["version"] == "1.0.3"
    assert c.post(f"/api/games/{gid}/fixed_replies", json={}, headers=H).status_code == 400  # nothing merged yet
    assert c.get("/api/feedback/9999").status_code == 404
    assert c.post("/api/feedback/scan", headers=H).status_code == 200
    assert c.post("/api/feedback/scan").status_code == 403  # CSRF header still required


def test_work_hours_caps_and_concurrency_guard(studio, fake):
    st = studio
    st.new_game("a")
    st.new_game("b")
    now = time.localtime()
    h = (now.tm_hour + 2) % 24
    st.db.set("work_hours", f"{h:02d}:00-{(h + 1) % 24:02d}:00")
    assert "outside work hours" in st.hold_reason() and process_one(st) is False
    st.db.set("work_hours", "")
    st.db.set("daily_run_cap", "1")
    assert process_one(st)
    assert "daily run cap" in st.hold_reason() and process_one(st) is False
    st.db.set("daily_run_cap", "0")
    # two runner threads never take two jobs of the same game
    gid = st.db.one("SELECT game_id FROM jobs WHERE status='queued'")["game_id"]
    st.enqueue(gid, "producer", "producer.standup", {})
    first = claim_next(st, ignore_schedule=True)
    second = claim_next(st, ignore_schedule=True)
    assert first["game_id"] == gid and second is None


def test_rate_limit_shows_engine_backoff(studio, fake):
    st = studio
    c = client(st)
    fake.script("designer.pitch", RateLimited("429 quota"))
    st.new_game("x")
    process_one(st)
    eb = c.get("/api/status").json()["engine_backoff"]
    assert "fake" in eb and eb["fake"]["remaining"] > 100 and "429" in eb["fake"]["reason"]
    d = next(a for a in c.get("/api/status").json()["agents"] if a["name"] == "designer")
    assert d["state"] == "queued" and d["backoff_jobs"] == 1
    run_until_idle(st)
    assert c.get("/api/status").json()["engine_backoff"] == {}


def test_standup_time_and_notifications(studio):
    st = studio
    st.db.set("standup_time", "09:30")
    assert standup_due(st, time.struct_time((2026, 10, 26, 9, 31, 0, 0, 299, 0)))
    assert not standup_due(st, time.struct_time((2026, 10, 26, 9, 29, 0, 0, 299, 0)))
    assert nt.in_range("22:30-07:30", time.struct_time((2026, 10, 26, 23, 0, 0, 0, 299, 0)))
    assert nt.in_range("22:30-07:30", time.struct_time((2026, 10, 26, 6, 0, 0, 0, 299, 0)))
    assert not nt.in_range("22:30-07:30", time.struct_time((2026, 10, 26, 12, 0, 0, 0, 299, 0)))
    sent = []
    base = {"notify_on": "approvals", "quiet_hours": "", "notify_desktop": "0", "notify_webhook": "1"}
    import os
    os.environ["STUDIO_NOTIFY_WEBHOOK"] = "https://ntfy.example/me"
    try:
        assert nt.notify(base, "approvals", "Gate 1", "x", sender=lambda u, t, m: sent.append((u, t))) == "sent"
        assert nt.notify(base, "errors", "e", "x", sender=lambda u, t, m: sent.append(1)) == "off"
        assert nt.notify(dict(base, quiet_hours="00:00-24:00"), "approvals", "q", "x", sender=lambda u, t, m: sent.append(1)) == "quiet"
    finally:
        del os.environ["STUDIO_NOTIFY_WEBHOOK"]
    assert sent == [("https://ntfy.example/me", "Gate 1")]
    # the studio calls the notifier on new approvals
    calls = []
    st.notifier = lambda s, kind, title, msg: calls.append(kind) or "sent"
    st.new_game("x")
    run_until_idle(st)
    assert "approvals" in calls


def test_demo_seed_runs_offline(tmp_path, monkeypatch):
    for k in ("STUDIO_ENGINE", "STUDIO_STANDUP_ENABLED", "STUDIO_MIN_SECONDS_BETWEEN_RUNS", "STUDIO_NOTIFY_DESKTOP", "STUDIO_PROMPTS"):
        monkeypatch.setenv(k, "")
    import studio.workflow as wf
    monkeypatch.setattr(wf, "find_godot", wf.find_godot)
    from studio.demo import seed
    st = seed(tmp_path / "demo")
    s = st.status()
    states = {a["name"]: a["state"] for a in s["agents"]}
    assert states["artist"] == "running" and states["marketing"] == "paused" and states["analyst"] == "error"
    assert s["approvals_waiting"]["6"] >= 5 and s["approvals_waiting"]["3"] >= 2 and s["engine_backoff"]
    assert st.db.one("SELECT COUNT(*) n FROM feedback_items")["n"] == 8
