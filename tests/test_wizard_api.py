"""Guided setup wizard endpoints: state, prerequisites, presets, per-role config, keys (masked, never stored in the
database), connection tests, studio identity, finish summary, and the UI wiring."""
import json

from fastapi.testclient import TestClient

from studio import wizard
from studio.app import create_app
from studio.wizard import check_prereqs, preset_roles
from test_providers import FakeHTTP

H = {"X-Studio": "1"}


def client(st):
    return TestClient(create_app(st, start_worker=False))


def test_setup_state_and_ui_wiring(studio):
    c = client(studio)
    s = c.get("/api/setup").json()
    assert s["complete"] is False and s["steps"][0] == "welcome" and s["steps"][-1] == "finish"
    assert set(s["presets"]) == {"google_pro", "claude_eng", "local_only", "mixed"}
    assert set(s["roles"]) == {"producer", "designer", "engineer", "artist", "qa", "marketing", "analyst", "support", "bugfixer"}
    ids = {p["id"] for p in s["providers"]}
    assert {"agy", "claude_code", "codex", "genai", "anthropic", "openai", "openrouter", "ollama", "lmstudio"} <= ids
    assert all(p["cost_note"] for p in s["providers"])
    assert s["identity"]["package_prefix"] == "com.ottranstudios" and s["identity"]["contact_email"] == "ottranstudios@gmail.com"
    assert c.get("/api/status").json()["setup_complete"] is False
    html = c.get("/").text
    assert 'data-tab="setup"' in html
    js = c.get("/static/app.js").text
    for fn in ("function vSetup", "wPrereqs", "wProviders", "wKeys", "wTest", "wIdentity", "wAccounts", "wFinish", "/api/setup/finish"):
        assert fn in js
    assert c.post("/api/setup/step", json={"step": "keys"}, headers=H).json()["step"] == "keys"
    assert c.get("/api/setup").json()["step"] == "keys"
    assert c.post("/api/setup/step", json={"step": "nope"}, headers=H).status_code == 400


def test_prereq_checks_report_fixes(studio, monkeypatch):
    have = {"git": "/usr/bin/git", "gh": "/opt/homebrew/bin/gh", "java": "/usr/bin/java", "godot": "/x/Godot"}

    def run(cmd):
        name = cmd[0].rsplit("/", 1)[-1]
        return {"git": (0, "git version 2.47.0"), "gh": (0 if cmd[1] == "--version" else 1, "gh version 2.80.0" if cmd[1] == "--version" else "not logged in"),
                "java": (0, 'openjdk version "17.0.12" 2024-07-16'), "Godot": (0, "4.3.stable.official")}[name]
    checks = {c["id"]: c for c in check_prereqs({}, run=run, find=lambda b: have.get(b), env={})}
    assert checks["python"]["ok"] and checks["git"]["ok"] and checks["jdk"]["ok"]
    assert not checks["godot"]["ok"] and "4.7" in checks["godot"]["fix"]           # 4.3 is too old
    assert not checks["android_sdk"]["ok"] and not checks["android_sdk"]["required"] and "sdkmanager" in checks["android_sdk"]["fix"]
    assert not checks["gh"]["ok"] and "gh auth login" in checks["gh"]["fix"]
    # through the API (wizard functions monkeypatched)
    monkeypatch.setattr(wizard, "_run", run)
    monkeypatch.setattr(wizard, "which", lambda b: have.get(b))
    monkeypatch.setattr(wizard, "find_godot", lambda configured="": "/x/Godot")
    r = client(studio).get("/api/setup/prereqs").json()
    assert r["ok"] is False and {c["id"] for c in r["checks"]} == {"python", "godot", "android_sdk", "jdk", "git", "gh"}


def test_presets_and_roles(studio):
    c = client(studio)
    r = c.post("/api/setup/preset", json={"preset": "local_only"}, headers=H).json()["roles"]
    assert all(v == {"engine": "ollama", "model": "qwen2.5-coder:7b"} for v in r.values())
    assert c.get("/api/setup").json()["preset"] == "local_only"
    p = preset_roles("claude_eng", have_bin=lambda b: b == "claude")
    assert p["engineer"]["engine"] == "claude_code" and p["qa"]["engine"] == "claude_code" and p["designer"]["engine"] == "agy"
    p = preset_roles("claude_eng", have_bin=lambda b: False)
    assert p["bugfixer"] == {"engine": "anthropic", "model": "claude-sonnet-5-5"}
    m = preset_roles("mixed", have_bin=lambda b: False)
    assert m["qa"]["engine"] == "openai" and m["support"]["engine"] == "genai" and m["producer"]["engine"] == "agy"
    assert preset_roles("google_pro")["artist"] == {"engine": "agy", "model": ""}
    assert c.post("/api/setup/preset", json={"preset": "bogus"}, headers=H).status_code == 400
    r = c.post("/api/setup/roles", json={"roles": {"engineer": {"engine": "openrouter", "model": "anthropic/claude-sonnet-5.5"}}}, headers=H)
    assert r.status_code == 200 and r.json()["roles"]["engineer"] == {"engine": "openrouter", "model": "anthropic/claude-sonnet-5.5"}
    assert studio.agent_cfg("engineer")["engine"] == "openrouter"
    assert c.post("/api/setup/roles", json={"roles": {"engineer": {"engine": "skynet"}}}, headers=H).status_code == 400
    assert c.post("/api/setup/roles", json={"roles": {"ceo": {"engine": "agy"}}}, headers=H).status_code == 404
    assert "openrouter" in studio.used_providers()


def test_keys_are_masked_and_never_stored_in_db(studio):
    c = client(studio)
    k = c.get("/api/setup/keys").json()
    assert k["backends"] == ["env"] and k["keys"]["ANTHROPIC_API_KEY"]["set"] is False
    secret = "sk-ant-api03-THIS-IS-A-FAKE-KEY-1234567890"   # secretscan: allow
    r = c.post("/api/setup/keys", json={"name": "ANTHROPIC_API_KEY", "value": secret, "backend": "env"}, headers=H)
    assert r.status_code == 200 and r.json()["masked"] == "sk-a...7890" and secret not in r.text
    for path in ("/api/setup", "/api/setup/keys", "/api/settings", "/api/status", "/api/providers", "/api/state"):
        assert secret not in c.get(path).text, path
    assert c.get("/api/setup/keys").json()["keys"]["ANTHROPIC_API_KEY"] == {"name": "ANTHROPIC_API_KEY", "set": True,
                                                                             "masked": "sk-a...7890", "source": ".env"}
    assert c.get("/api/settings").json()["secrets"]["ANTHROPIC_API_KEY"] == "set"
    assert secret not in json.dumps(studio.db.all("SELECT * FROM settings"))
    assert secret not in json.dumps(studio.db.all("SELECT * FROM events"))
    assert secret in studio.secrets.env_file.read_text()                     # only in the gitignored .env
    assert c.post("/api/setup/keys", json={"name": "PATH", "value": "x", "backend": "env"}, headers=H).status_code == 400
    assert c.post("/api/setup/keys", json={"name": "OPENAI_API_KEY", "value": "x", "backend": "keychain"}, headers=H).status_code == 400
    assert c.post("/api/setup/keys", json={"name": "OPENAI_API_KEY", "value": "a\nb", "backend": "env"}, headers=H).status_code == 400


def test_test_connection_endpoint(studio):
    c = client(studio)
    studio.http_transport = FakeHTTP({":generateContent": (200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}],
                                                                 "usageMetadata": {"totalTokenCount": 3}}),
                                      "/models": (200, {"models": [{"name": "models/gemini-3.8-flash"}]})})
    r = c.post("/api/providers/genai/test", json={}, headers=H).json()
    assert r["ok"] is False and "GEMINI_API_KEY" in r["detail"]            # no key yet: clear message + fix
    c.post("/api/setup/keys", json={"name": "GEMINI_API_KEY", "value": "AIzaFAKEFAKEFAKE", "backend": "env"}, headers=H)
    r = c.post("/api/providers/genai/test", json={}, headers=H).json()
    assert r["ok"] and "1 models visible" in r["detail"] and "latency_ms" in r
    r = c.post("/api/providers/genai/test", json={"deep": True}, headers=H).json()
    assert r["ok"] and "replied 'OK'" in r["detail"]
    assert "AIzaFAKE" not in json.dumps(r)
    assert c.post("/api/providers/fake/test", json={}, headers=H).json()["ok"]
    assert c.post("/api/providers/warp/test", json={}, headers=H).json()["ok"] is False
    assert c.post("/api/providers/genai/test", json={}).status_code == 403      # CSRF header still required


def test_identity_validation_and_finish_summary(studio):
    c = client(studio)
    bad = {"studio_name": "Ottran Studios", "package_prefix": "com.studio", "contact_email": "ottranstudios@gmail.com"}
    assert c.post("/api/setup/identity", json=bad, headers=H).status_code == 400
    assert c.post("/api/setup/identity", json={**bad, "package_prefix": "Com Ottran"}, headers=H).status_code == 400
    assert c.post("/api/setup/identity", json={**bad, "package_prefix": "com.ottran", "contact_email": "nope"}, headers=H).status_code == 400
    assert c.post("/api/setup/identity", json={**bad, "package_prefix": "com.ottran", "studio_website": "http://x.com"}, headers=H).status_code == 400
    good = {"studio_name": "Ottran Studios", "package_prefix": "com.ottranstudios", "contact_email": "ottranstudios@gmail.com",
            "studio_website": "https://ottranstudios.com/", "github_owner": "dharasudhan", "play_account_type": "personal"}
    r = c.post("/api/setup/identity", json=good, headers=H)
    assert r.status_code == 200 and r.json()["studio_website"] == "https://ottranstudios.com"
    c.post("/api/setup/preset", json={"preset": "mixed"}, headers=H)
    s = c.post("/api/setup/finish", headers=H).json()
    assert len(s["roles"]) == 9 and s["identity"]["github_owner"] == "dharasudhan"
    assert any("GEMINI_API_KEY" in m for m in s["missing"])
    assert c.get("/api/status").json()["setup_complete"] is True
    # identity reaches new game repos (package id from the prefix) and agent prompts
    from studio.worker import run_until_idle
    from conftest import pending
    gid = studio.new_game("cozy ferry puzzle")
    studio.set_agent("designer", engine="fake")
    studio.set_agent("producer", engine="fake")
    run_until_idle(studio)
    studio.approve(pending(studio, 1)[0]["id"])
    g = studio.game(gid)
    assert g["package"] == "com.ottranstudios.orbit_hopper"
    assert "Studio: Ottran Studios | package ids com.ottranstudios.<slug>" in studio.db.one("SELECT prompt FROM runs ORDER BY id LIMIT 1")["prompt"]
