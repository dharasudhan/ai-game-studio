"""1.6.0 Gemini Decisions API: support triage without an LLM run, QA screenshot pre-check, off by default."""
import json

from studio import decisions as dc
from studio.godot import QAReport
from studio.worker import maybe_scan_feedback, run_until_idle
from conftest import pending, released_game
from test_support import drop


def _transport(answers_for, log=None):
    def t(method, url, headers, body, timeout):
        req = json.loads(body)
        if log is not None:
            log.append((url, headers, req))
        assert url.endswith("/v1beta/decisions") and req["model"] == "gemini-decision-1"
        return 200, json.dumps({"answers": answers_for(req), "usage": {"total_input_tokens": 50, "total_output_tokens": 0}}).encode()
    return t


def _triage_answers(cat, conf, needs, sev_level=0):
    def f(req):
        probs = {str(i): (0.9 if i == sev_level else 0.1 / 3) for i in range(4)}
        return {"category": {"type": "choice", "choice": cat, "confidence": conf, "probabilities": {cat: conf}},
                "severity": {"type": "score", "score": float(sev_level), "probabilities": probs, "confidence": 0.9},
                "sentiment": {"type": "choice", "choice": "positive", "confidence": 0.9},
                "needs_reply": {"type": "noul", "noul": needs, "confidence": max(needs, 1 - needs)}}
    return f


def test_client_payload_and_triage_parsing():
    log = []
    cl = dc.DecisionsClient("k-test", transport=_transport(_triage_answers("crash", 0.95, 0.9, 3), log))
    r = dc.triage_item(cl, "Help", "Crashes on start every time", 1)
    assert r["category"] == "crash" and r["severity"] == "critical" and r["needs_reply"] == 0.9
    url, headers, req = log[0]
    assert headers["x-goog-api-key"] == "k-test"
    assert set(req["questions"]) == {"category", "severity", "sentiment", "needs_reply"}
    assert "Crashes on start" in req["input"][0]["text"], "player text is input data, never a question"
    assert all("Crashes" not in q["instructions"] for q in req["questions"].values())


def test_off_by_default_and_needs_a_key():
    get = {"GEMINI_API_KEY": "k"}.get
    assert dc.client_from_settings({}, get) is None
    assert dc.client_from_settings({"decisions_checks": "1"}, lambda k: None) is None
    assert dc.client_from_settings({"decisions_checks": "1"}, get) is not None


def test_screenshot_precheck_flags_blank_frame(tmp_path):
    shot = tmp_path / "shot_01.png"
    shot.write_bytes(b"\x89PNG fake")
    log = []
    bad = lambda req: {"blank_frame": {"type": "noul", "noul": 0.97}, "text_clipped": {"type": "noul", "noul": 0.1},  # noqa: E731
                       "ui_overlap": {"type": "noul", "noul": 0.2}}
    ok, detail, probs = dc.check_screenshots(dc.DecisionsClient("k", transport=_transport(bad, log)), [str(shot)])
    assert ok is False and "blank" in detail and probs["blank_frame"] == 0.97
    img = [b for b in log[0][2]["input"] if b["type"] == "image"][0]
    assert img["mime_type"] == "image/png" and img["data"]
    good = lambda req: {k: {"type": "noul", "noul": 0.05} for k in req["questions"]}  # noqa: E731
    assert dc.check_screenshots(dc.DecisionsClient("k", transport=_transport(good)), [str(shot)])[0] is True


def test_studio_shot_check_adds_qa_row(studio, tmp_path, monkeypatch):
    st = studio
    shot = tmp_path / "shot_01.png"
    shot.write_bytes(b"\x89PNG fake")
    rep = QAReport(shots=[str(shot)])
    assert st.decisions_shot_check(rep) is None and not rep.checks, "off by default: no call, no row"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    st.db.set("decisions_checks", "1")
    st.http_transport = _transport(lambda req: {k: {"type": "noul", "noul": 0.9 if k == "ui_overlap" else 0.1}
                                                for k in req["questions"]})
    assert st.decisions_shot_check(rep) is False and rep.passed is False
    assert "HUD" in rep.markdown()


def test_confident_no_reply_items_skip_the_support_llm(studio, fake, monkeypatch):
    st = studio
    released_game(st)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    st.db.set("decisions_checks", "1")
    st.http_transport = _transport(_triage_answers("praise", 0.96, 0.04))
    drop(st, "praise.txt", "Lovely little game, five stars", "orbit-hopper")
    before = sum(1 for c in fake.calls if c.task == "support.triage")
    assert maybe_scan_feedback(st, force=True)
    run_until_idle(st)
    item = st.db.one("SELECT * FROM feedback_items")
    assert item["category"] == "praise" and item["reply_draft"] is None and item["status"] == "triaged"
    assert sum(1 for c in fake.calls if c.task == "support.triage") == before, "no LLM run spent on it"
    assert not [a for a in pending(st, 6) if a["kind"] == "reply"]


def test_items_needing_a_reply_still_get_a_draft(studio, fake, monkeypatch):
    st = studio
    released_game(st)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    st.db.set("decisions_checks", "1")
    st.http_transport = _transport(_triage_answers("billing", 0.93, 0.95, 2))
    drop(st, "bill.txt", "From: ana@example.com\n\nI paid for remove ads and still see ads", "orbit-hopper")
    assert maybe_scan_feedback(st, force=True)
    run_until_idle(st)
    item = st.db.one("SELECT * FROM feedback_items")
    assert item["category"] == "billing" and item["severity"] == "high" and item["reply_draft"]
    assert any(c.task == "support.triage" for c in fake.calls)
