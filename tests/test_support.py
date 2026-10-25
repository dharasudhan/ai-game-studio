"""Customer Support agent: ingestion (Play CSV UTF-16, inbox txt/json/csv, in-game JSON, IMAP), dedup,
classification with the fake engine, grouping, Gate 6 reply drafts (never posted), redraft on rejection."""
import json
import shutil
from email.message import EmailMessage
from pathlib import Path

import pytest

from studio import support as sp
from studio.db import loads
from studio.worker import maybe_scan_feedback, run_until_idle
from conftest import pending, released_game

FIX = Path(__file__).parent / "fixtures"
PLAY = FIX / "reviews_com.ottranstudios.orbit_hopper_202610.csv"


def test_play_csv_utf16_parsed_by_column_name(tmp_path):
    items = sp.parse_file(PLAY, FIX)
    assert len(items) == 4  # the star-only review (no text) is skipped
    first = items[0]
    assert first.source == "play" and first.rating == 1 and first.app_version == "1.0.2"
    assert first.game_hint == "com.ottranstudios.orbit_hopper" and first.external_id.endswith("id=r1")
    assert first.reply_channel == "play" and first.device == "a52q"


def test_txt_json_generic_csv(tmp_path):
    (tmp_path / "orbit-hopper").mkdir()
    t = tmp_path / "orbit-hopper" / "mail.txt"
    t.write_text("From: ana@example.com\nVersion: 1.0.2\n\nI was charged twice for remove ads\n---\nGame: other\n\nadd dark mode")
    items = sp.parse_file(t, tmp_path)
    assert [i.author for i in items] == ["ana@example.com", ""]
    assert items[0].game_hint == "orbit-hopper" and items[1].game_hint == "other" and items[0].reply_channel == "email"
    j = tmp_path / "ingame.json"
    j.write_text(json.dumps({"game": "orbit-hopper", "version": "1.0.2", "items": [{"message": "stuck on level 4", "type": "bug", "log": "ERR null"}]}))
    ji = sp.parse_file(j, tmp_path)
    assert ji[0].category_hint == "bug" and "Log:" in ji[0].text and ji[0].app_version == "1.0.2"
    c = tmp_path / "survey.csv"
    c.write_text("Message,Stars,Version\nGreat fun,5,1.0\n,3,1.0\n")
    assert [i.text for i in sp.parse_file(c, tmp_path)] == ["Great fun"]


def test_rule_classifier_and_fingerprint():
    assert sp.rule_classify("Game crashes every time on launch", 1) == {"category": "crash", "sentiment": "negative", "severity": "critical"}
    assert sp.rule_classify("I was charged but got nothing, refund please", 1)["category"] == "billing"
    assert sp.rule_classify("way too many ads", 2)["category"] == "ads"
    assert sp.rule_classify("please add a dark mode", 5)["category"] == "feature_request"
    assert sp.rule_classify("love it, so relaxing", 5)["category"] == "praise"
    assert sp.rule_classify("you idiot, free coins at telegram.me/x", 1)["category"] == "abuse"
    assert sp.rule_classify("level 3 is broken", 3)["category"] == "bug"
    assert sp.rule_classify("whatever", None, hint="feature")["category"] == "feature_request"
    # same text with different numbers/urls/case -> same fingerprint; different text -> different
    assert sp.fingerprint("Crash at 12:01 on https://x.y", "A") == sp.fingerprint("crash at 9:15 on www.z.com", "a")
    assert sp.fingerprint("crash on level", "a") != sp.fingerprint("lag on level", "a")
    assert sp.jaccard(sp.tokens("crashes when level 3 loads"), sp.tokens("game crashed loading level 3")) > 0.34


def drop(st, name, content, sub=""):
    d = st.feedback_dir() / sub if sub else st.feedback_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content)
    return p


def test_ingest_classify_group_and_draft_replies(studio, fake):
    st = studio
    gid = released_game(st)
    assert st.game(gid)["package"] == "com.ottranstudios.orbit_hopper"
    shutil.copy(PLAY, st.feedback_dir() / PLAY.name)
    drop(st, "dupe.txt", "Game crashes every time I open level 3. Unplayable", "orbit-hopper")  # different author -> kept
    drop(st, "abuse.txt", "you idiot, free coins at telegram.me/spam", "orbit-hopper")
    drop(st, "bill.txt", "From: ana@example.com\n\nI was charged twice for remove ads", "orbit-hopper")
    drop(st, "bill-again.txt", "From: ana@example.com\n\nI was charged twice for remove ads!!", "orbit-hopper")  # exact dup after normalising
    assert maybe_scan_feedback(st, force=True)
    run_until_idle(st)

    items = st.db.all("SELECT * FROM feedback_items ORDER BY id")
    assert len(items) == 7
    assert all(i["game_id"] == gid for i in items)
    assert st.db.one("SELECT duplicates FROM feedback_items WHERE author='ana@example.com'")["duplicates"] == 1
    cats = {i["text"][:20]: i["category"] for i in items}
    assert cats["Game crashes every t"] == "crash" and cats["Love this game, so r"] == "feature_request"
    assert cats["Too many ads, an ad "] == "ads" and cats["I was charged twice "] == "billing"
    assert cats["you idiot, free coin"] == "abuse"
    crash = [i for i in items if i["category"] == "crash"]
    assert len(crash) == 3 and len({i["group_id"] for i in crash}) == 1, "similar crash reports share one group"
    grp = st.db.one("SELECT * FROM feedback_groups WHERE id=?", crash[0]["group_id"])
    assert grp["count"] == 3 and grp["severity"] == "critical"

    # replies are drafts waiting at Gate 6, one per non-abuse item; nothing was posted
    g6 = [a for a in pending(st, 6) if a["kind"] == "reply"]
    assert len(g6) == 6
    abuse = [i for i in items if i["category"] == "abuse"][0]
    assert abuse["reply_draft"] is None and abuse["status"] == "triaged"
    chans = {loads(a["payload_json"])["channel"] for a in g6}
    assert {"Google Play review reply", "Email reply to ana@example.com"} <= chans
    p = next(loads(a["payload_json"]) for a in g6 if loads(a["payload_json"])["review_link"])
    assert p["content"] and p["player_text"]
    assert all(i["status"] == "awaiting_approval" for i in items if i["category"] != "abuse")

    # the crash group went to the Bug Fixer -> bug ticket -> fix -> QA -> Gate 3
    t = st.db.one("SELECT * FROM tickets WHERE kind='bug'")
    assert t and t["agent"] == "bugfixer" and t["repro_steps"] and t["feedback_group_id"] == grp["id"]
    assert all(i["bug_ticket_id"] == t["id"] for i in st.db.all("SELECT * FROM feedback_items WHERE category='crash'"))
    assert len([a for a in pending(st, 3)]) == 1

    # re-scanning unchanged files adds nothing; an edited review is re-triaged
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    assert st.db.one("SELECT COUNT(*) n FROM feedback_items")["n"] == 7
    raw = PLAY.read_bytes().decode("utf-16").replace("Too many ads, an ad after every level", "Ads are fine now, thanks!")
    drop(st, PLAY.name, raw.encode("utf-16"))
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    ed = st.db.one("SELECT * FROM feedback_items WHERE external_id LIKE '%id=r5'")
    assert ed["text"].startswith("Ads are fine") and ed["category"] is not None
    assert st.db.one("SELECT COUNT(*) n FROM feedback_items")["n"] == 7


def test_reply_gate6_reject_redraft_then_approve(studio, fake):
    st = studio
    released_game(st)
    drop(st, "a.txt", "Game: orbit-hopper\n\nplease add more levels, love it")
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    a = [x for x in pending(st, 6) if x["kind"] == "reply"][0]
    item_id = loads(a["payload_json"])["item_id"]
    with pytest.raises(ValueError):
        st.set_feedback_status(item_id, "replied")  # cannot claim it was posted before Gate 6
    st.reject(a["id"], "Mention the level editor is coming")
    run_until_idle(st)
    redraft = [c for c in fake.calls if c.task == "support.redraft_reply"]
    assert redraft and "Mention the level editor is coming" in redraft[-1].prompt
    a2 = [x for x in pending(st, 6) if x["kind"] == "reply"][0]
    assert "fixed this" in loads(a2["payload_json"])["content"]
    st.edit_reply_draft(item_id, "Thanks! More levels are on the way.")
    assert loads(st.db.one("SELECT payload_json FROM approvals WHERE id=?", a2["id"])["payload_json"])["content"] == "Thanks! More levels are on the way."
    st.approve(a2["id"])
    it = st.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
    assert it["status"] == "reply_approved" and it["reply_draft"] == "Thanks! More levels are on the way."
    assert st.set_feedback_status(item_id, "replied")["status"] == "replied"
    # rejection note is part of the Support agent's feedback memory
    assert any("level editor" in n["note"] for n in st.agent_feedback("support"))


def test_unlinked_feedback_and_manual_game_link(studio):
    st = studio
    gid = released_game(st)
    drop(st, "x.txt", "the app crashes on launch")  # no game hint at all
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    it = st.db.one("SELECT * FROM feedback_items")
    assert it["game_id"] is None and it["category"] == "crash" and it["bug_ticket_id"] is None
    st.set_feedback_game(it["id"], gid)
    assert st.db.one("SELECT game_id FROM feedback_items")["game_id"] == gid
    assert st.db.one("SELECT COUNT(*) n FROM jobs WHERE kind='bugfix.intake'")["n"] == 1


def test_game_map_setting_links_by_keyword(studio):
    st = studio
    gid = released_game(st)
    st.db.set("feedback_game_map", json.dumps({"hopper": "orbit-hopper"}))
    drop(st, "y.txt", "Subject: Hopper keeps lagging\n\nlags a lot")
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    assert st.db.one("SELECT game_id FROM feedback_items")["game_id"] == gid


class FakeIMAP:
    """Minimal imaplib stand-in: records read-only select and PEEK fetches."""
    log = []

    def __init__(self, host, port):
        FakeIMAP.log.append(("connect", host, port))
        m = EmailMessage()
        m["From"] = "Bo <bo@example.com>"
        m["Subject"] = "Orbit Hopper crash"
        m["Message-ID"] = "<m1@example.com>"
        m["Date"] = "Mon, 05 Oct 2026 10:00:00 +0000"
        m.set_content("It crashes when I open the shop.\n\nOn Mon someone wrote:\n> old quoted text")
        self.msg = bytes(m)

    def login(self, u, p):
        FakeIMAP.log.append(("login", u))

    def select(self, folder, readonly=False):
        FakeIMAP.log.append(("select", folder, readonly))
        return "OK", [b"1"]

    def search(self, charset, *crit):
        return "OK", [b"1"]

    def fetch(self, i, what):
        FakeIMAP.log.append(("fetch", what))
        return "OK", [(b"1", self.msg)]

    def logout(self):
        pass


def test_imap_source_read_only(studio, monkeypatch):
    st = studio
    gid = released_game(st)
    st.db.set("feedback_imap_enabled", "1")
    st.enqueue(None, "support", "support.ingest", {})
    run_until_idle(st)
    assert any("IMAP" in e["message"] for e in st.db.all("SELECT message FROM events WHERE level='error'"))  # no creds -> reported
    monkeypatch.setenv("STUDIO_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("STUDIO_IMAP_USER", "support@example.com")
    monkeypatch.setenv("STUDIO_IMAP_PASSWORD", "x")
    st.imap_factory = FakeIMAP
    for _ in range(2):  # second scan: same Message-ID -> no duplicate
        st.enqueue(None, "support", "support.ingest", {})
        run_until_idle(st)
    rows = st.db.all("SELECT * FROM feedback_items WHERE source='imap'")
    assert len(rows) == 1
    it = rows[0]
    assert it["author"] == "bo@example.com" and it["game_id"] == gid and "quoted" not in it["text"]
    assert it["reply_channel"] == "email" and it["category"] == "crash"
    assert ("select", "INBOX", True) in FakeIMAP.log and ("fetch", "(BODY.PEEK[])") in FakeIMAP.log
    a = [x for x in pending(st, 6) if x["kind"] == "reply"][0]
    assert loads(a["payload_json"])["channel"] == "Email reply to bo@example.com"


def test_ingame_api_payload_and_upload(studio):
    st = studio
    released_game(st)
    st.add_ingame_feedback({"game": "orbit-hopper", "message": "music stops after level 2", "type": "bug", "version": "1.0.3"})
    with pytest.raises(ValueError):
        st.add_feedback_file("evil.exe", b"x")
    run_until_idle(st)
    it = st.db.one("SELECT * FROM feedback_items")
    assert it["source"] == "ingame" and it["category"] == "bug" and it["app_version"] == "1.0.3"
