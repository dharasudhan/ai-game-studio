"""Standing rule: the launch-readiness audit runs before every store upload and its blockers keep Gate 5 closed.
Also covers the deterministic checks, the PDF, the secret scan, and the Godot 4.7 / Ottran Studios template."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio import gitops
from studio.app import create_app
from studio.audit import deterministic_checks, read_preset, summarize
from studio.pdfgen import markdown_to_pdf
from studio.secretscan import scan
from studio.worker import run_until_idle
from conftest import pending

H = {"X-Studio": "1"}


def to_release(st):
    gid = st.new_game("A one-thumb space hopper for Android", "Hopper")
    run_until_idle(st)
    st.approve(pending(st, 1)[0]["id"])
    run_until_idle(st)
    st.approve(pending(st, 2)[0]["id"])
    run_until_idle(st)
    st.approve(pending(st, 3)[0]["id"])      # merge -> milestone done -> release build -> audit -> release kit
    run_until_idle(st)
    return gid


def edit_main(repo: Path, rel: str, old: str, new: str, msg: str) -> None:
    p = repo / rel
    p.write_text(p.read_text().replace(old, new))
    gitops.git(repo, "add", "-A")
    gitops.git(repo, "commit", "-q", "-m", msg)


def test_release_runs_audit_and_clean_audit_opens_gate5(studio, fake):
    st = studio
    gid = to_release(st)
    kinds = [j["kind"] for j in st.db.all("SELECT kind FROM jobs ORDER BY id")]
    assert kinds.index("qa.release_build") < kinds.index("qa.launch_audit") < kinds.index("marketing.release_kit")
    au = st.latest_audit(gid)
    assert au and au["verdict"] == "READY" and au["blockers"] == 0 and au["version_code"] == 1
    pdf = Path(au["pdf_path"])
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF-1.4") and pdf.name == "launch_audit_v0.1.0.pdf"
    items = json.loads(au["items_json"])
    assert any(i["source"] == "agent" for i in items) and any(i["source"] == "checklist" for i in items)
    assert any("12 testers" in i["check"] for i in items) and any("JPEG" in i["check"] for i in items)
    md = au["markdown"]
    assert md.index("## Blockers") < md.index("## Other findings")
    audit_call = [c for c in fake.calls if c.task == "qa.launch_audit"][0]
    assert "Automated checks already done" in audit_call.prompt and audit_call.edit is False
    g5 = pending(st, 5)[0]
    p = json.loads(g5["payload_json"])
    assert p["audit_verdict"] == "READY" and p["audit_blockers"] == 0 and p["audit_pdf"] == str(pdf)
    kit_call = [c for c in fake.calls if c.task == "marketing.release_kit"][-1]
    assert "ottranstudios@gmail.com" in kit_call.prompt and "https://ottranstudios.com" in kit_call.prompt
    assert st.release_block_reason(gid) == ""
    st.approve(g5["id"])
    g = st.game(gid)
    assert g["status"] == "released" and g["released_version_code"] == 1
    # the next upload needs a bumped versionCode: re-auditing the same build now has a blocker
    st.request_audit(gid)
    run_until_idle(st)
    assert st.latest_audit(gid)["blockers"] >= 1
    assert any("versionCode 1 is higher" in i["check"] and i["blocker"] for i in json.loads(st.latest_audit(gid)["items_json"]))


def test_audit_blockers_block_gate5_upload(studio, fake):
    st = studio
    gid = to_release(st)
    repo = Path(st.game(gid)["repo_path"])
    g5 = pending(st, 5)[0]
    # the owner (or an agent) changes the package id to an old-style one on main and bumps nothing
    edit_main(repo, "export_presets.cfg", 'package/unique_name="com.ottranstudios.', 'package/unique_name="com.studio.', "bad pkg")
    fake.script("qa.launch_audit", '```json\n{"summary":"Startup 9 s","items":[{"area":"performance","check":"Startup under 5 s",'
                                   '"verdict":"FAIL","blocker":true,"fix":"Lazy-load the level atlas"}]}\n```')
    st.request_audit(gid)
    run_until_idle(st)
    au = st.latest_audit(gid)
    assert au["verdict"] == "BLOCKED" and au["blockers"] == 2
    assert au["markdown"].index("Lazy-load the level atlas") < au["markdown"].index("## Other findings")
    c = TestClient(create_app(st, start_worker=False))
    r = c.post(f"/api/approvals/{g5['id']}/approve", headers=H)
    assert r.status_code == 400 and "Launch audit blocks the upload" in r.json()["detail"] and "2 open blocker" in r.json()["detail"]
    assert st.db.one("SELECT status FROM approvals WHERE id=?", g5["id"])["status"] == "pending"   # still waiting, not lost
    assert st.game(gid)["status"] != "released"
    info = c.get(f"/api/games/{gid}/audit").json()
    assert info["audit"]["blockers"] == 2 and "blocker" in info["block_reason"]
    assert c.get(f"/api/audits/{au['id']}/pdf").content.startswith(b"%PDF")
    # fix on main, bump the build, re-run the audit from the API -> Gate 5 opens
    edit_main(repo, "export_presets.cfg", 'package/unique_name="com.studio.', 'package/unique_name="com.ottranstudios.', "fix pkg")
    jid = c.post(f"/api/games/{gid}/audit", headers=H).json()["job_id"]
    assert jid
    run_until_idle(st)
    assert st.latest_audit(gid)["blockers"] == 0
    assert c.post(f"/api/approvals/{g5['id']}/approve", headers=H).status_code == 200
    assert st.game(gid)["status"] == "released"


def test_stale_or_missing_audit_blocks_and_setting_can_turn_rule_off(studio):
    st = studio
    gid = to_release(st)
    repo = Path(st.game(gid)["repo_path"])
    edit_main(repo, "export_presets.cfg", "version/code=1", "version/code=2", "bump")
    assert "versionCode 1 but the build is 2" in st.release_block_reason(gid)
    with pytest.raises(ValueError):
        st.approve(pending(st, 5)[0]["id"])
    st.db.execute("DELETE FROM audits") if hasattr(st.db, "execute") else st.db.conn().execute("DELETE FROM audits")
    assert "no launch-readiness audit" in st.release_block_reason(gid)
    st.db.set("audit_required_for_release", "0")
    assert st.release_block_reason(gid) == ""
    st.approve(pending(st, 5)[0]["id"])
    assert st.game(gid)["status"] == "released"


def test_deterministic_checks_cover_play_and_compliance_lessons(tmp_path):
    repo = tmp_path / "g"
    (repo / "config").mkdir(parents=True)
    (repo / "store" / "screenshots").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "export_presets.cfg").write_text('package/unique_name="com.ferryout.game"\nversion/code=3\nversion/name="0.9"\n'
                                             'gradle_build/target_sdk="34"\narchitectures/arm64-v8a=false\n'
                                             'keystore/release="/Users/m/upload.keystore"\n')
    (repo / "config" / "legal.json").write_text(json.dumps({"privacy_policy_url": "https://ottranstudios.com/g/privacy-policy.html",
                                                            "contact_email": "old@example.com"}))
    (repo / "store" / "screenshots" / "01_screenshot.png").write_bytes(b"\x89PNG")
    (repo / "scripts" / "ads.gd").write_text("var admob = null\nfunc show(): admob.load_banner()\n")
    (repo / "upload.jks").write_bytes(b"\x00key")
    s = {"package_prefix": "com.ottranstudios", "play_target_sdk": "36", "contact_email": "ottranstudios@gmail.com",
         "studio_name": "Ottran Studios", "audit_fetch_privacy_policy": "1"}
    items = deterministic_checks(repo, "g", s, "**QA FAILED**", released_code=3,
                                 fetch=lambda url: (200, "<p>Package: com.other.app</p>"))
    fails = {i["check"].split(" ")[0] + "|" + i["area"]: i for i in items if i["verdict"] == "FAIL"}
    text = json.dumps(items)
    blockers = [i["check"] for i in items if i["blocker"]]
    assert any("com.ferryout.game uses the studio prefix" in b for b in blockers)
    assert any("versionCode 3 is higher than the last released 3" in b for b in blockers)
    assert any("Target SDK 34" in b for b in blockers) and any("64-bit" in b for b in blockers)
    assert any("No release keystore" in b for b in blockers) and any("Secret scan" in b for b in blockers)
    assert any("intro" in b for b in blockers) and any("names the package id" in b for b in blockers)
    assert any("UMP consent" in b for b in blockers) and any("CREDITS.md" in b for b in blockers)
    assert any("Release QA" in b for b in blockers)
    assert "Store screenshots are JPEG" in text and "Contact email in the game" in text
    assert summarize(items)["verdict"] == "BLOCKED" and fails
    assert read_preset(repo)["version/code"] == "3"


def test_secret_scan_and_pdf(tmp_path):
    (tmp_path / "ok.gd").write_text("var x = 1\n")
    (tmp_path / "leak.cfg").write_text('key = "AIzaSyA1234567890abcdefghijklmnopqrstuv"\n')   # secretscan: allow
    (tmp_path / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")              # secretscan: allow
    (tmp_path / "release.keystore").write_bytes(b"\x00")
    (tmp_path / ".env").write_text("X=1\n")
    kinds = {(f["file"], f["kind"]) for f in scan(tmp_path)}
    assert ("leak.cfg", "Google API key") in kinds and ("id_rsa", "private key") in kinds
    assert any(f == "release.keystore" for f, _ in kinds) and any(f == ".env" for f, _ in kinds)
    assert not any(f == "ok.gd" for f, _ in kinds)
    pdf = markdown_to_pdf("# Title\n\n## Blockers\n- one (é ✓ unicode safe)\n" + "\n".join(f"- line {i}" for i in range(200)),
                          tmp_path / "r.pdf", "Report")
    b = pdf.read_bytes()
    assert b.startswith(b"%PDF-1.4") and b.rstrip().endswith(b"%%EOF") and b.count(b"/Type /Page ") >= 2


def test_new_game_repo_uses_godot47_ottran_template(studio):
    st = studio
    gid = st.new_game("cozy ferry puzzle")
    run_until_idle(st)
    st.approve(pending(st, 1)[0]["id"])
    repo = Path(st.game(gid)["repo_path"])
    proj = (repo / "project.godot").read_text()
    assert '"4.7"' in proj and 'run/main_scene="res://addons/studio_intro/studio_intro.tscn"' in proj and "StudioLoader=" in proj
    pre = read_preset(repo)
    assert pre["package/unique_name"] == "com.ottranstudios.orbit_hopper" and pre["gradle_build/target_sdk"] == "36"
    legal = json.loads((repo / "config" / "legal.json").read_text())
    assert legal["contact_email"] == "ottranstudios@gmail.com" and legal["privacy_policy_url"] == "https://ottranstudios.com/orbit-hopper/privacy-policy.html"
    assert (repo / "addons" / "studio_intro" / "audio" / "jingle.ogg").stat().st_size > 1000   # binaries copied intact
    gi = (repo / ".gitignore").read_text()
    for pat in ("*.keystore", "*.jks", "*.aab", ".env", "keys/"):
        assert pat in gi
    assert "{{" not in proj + (repo / "AGENTS.md").read_text() + (repo / "CREDITS.md").read_text()
    assert scan(repo) == []


def test_launch_law_checks_flag_remote_fonts_and_session_replay(tmp_path):
    """Tweet-driven 1.3.1 additions: remote Google Fonts/CDN = blocker, session replay SDK = TODO, six checklist rows."""
    repo = tmp_path / "g"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "index.html").write_text(
        '<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">\n'
        '<script src="https://static.hotjar.com/c/hotjar.js"></script>\n')
    s = {"package_prefix": "com.ottranstudios", "play_target_sdk": "36", "contact_email": "ottranstudios@gmail.com"}
    items = deterministic_checks(repo, "g", s, "", released_code=0, fetch=lambda url: (200, ""))
    by = {i["check"]: i for i in items}
    fonts = by["No fonts or scripts loaded from Google Fonts/CDNs at runtime (bundled only)"]
    assert fonts["verdict"] == "FAIL" and fonts["blocker"] and "fonts.googleapis.com" in fonts["fix"]
    replay = by["No session-replay SDK (or it waits for opt-in consent with input masking)"]
    assert replay["verdict"] == "TODO" and "hotjar" in replay["fix"].lower()
    text = json.dumps(items)
    for word in ("COPPA", "Munich", "CIPA", "CAN-SPAM", "renewal period", "DMCA agent"):
        assert word in text


def test_bundled_fonts_pass(tmp_path):
    repo = tmp_path / "g"
    (repo / "fonts").mkdir(parents=True)
    (repo / "main.gd").write_text('var f = load("res://fonts/Inter.ttf")\n')
    items = deterministic_checks(repo, "g", {}, "", released_code=0, fetch=lambda url: (200, ""))
    by = {i["check"]: i["verdict"] for i in items}
    assert by["No fonts or scripts loaded from Google Fonts/CDNs at runtime (bundled only)"] == "PASS"
    assert by["No session-replay SDK (or it waits for opt-in consent with input masking)"] == "PASS"
