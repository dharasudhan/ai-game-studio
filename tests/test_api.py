from fastapi.testclient import TestClient

from studio.app import create_app
from studio.worker import run_until_idle

H = {"X-Studio": "1"}


def test_dashboard_and_api(studio):
    c = TestClient(create_app(studio, start_worker=False))
    assert "Approval Desk" in c.get("/").text
    assert c.post("/api/games", json={"goal": "x"}).status_code == 403  # CSRF header required
    r = c.post("/api/games", json={"goal": "cozy fishing game"}, headers=H)
    assert r.status_code == 200
    run_until_idle(studio)
    s = c.get("/api/state").json()
    assert len(s["approvals"]) == 1 and s["approvals"][0]["gate"] == 1
    aid = s["approvals"][0]["id"]
    assert c.post(f"/api/approvals/{aid}/reject", json={"note": ""}, headers=H).status_code == 400
    assert c.post(f"/api/approvals/{aid}/approve", headers=H).status_code == 200
    assert c.post(f"/api/approvals/{aid}/approve", headers=H).status_code == 400
    assert c.post("/api/pause", headers=H).json()["paused"] is True
    assert c.get("/api/state").json()["settings"]["paused"] == "1"
    c.post("/api/resume", headers=H)
    assert c.post("/api/settings", json={"bogus": 1}, headers=H).status_code == 400
    assert c.post("/api/settings", json={"min_seconds_between_runs": "9"}, headers=H).json()["min_seconds_between_runs"] == "9"
    gid = s["games"][0]["id"]
    r = c.post(f"/api/games/{gid}/inbox", files={"file": ("crash.txt", b"NPE at level 2")}, headers=H)
    assert r.status_code == 200
    run_id = c.get("/api/state").json()["runs"][0]["id"]
    assert "TASK:" in c.get(f"/api/runs/{run_id}").json()["prompt"]
    assert "engineer" in c.get("/api/prompts").json()
