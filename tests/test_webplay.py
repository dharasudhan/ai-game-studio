"""Web QA (1.7.0): headless browser play check and seeded replay for web games."""
import json
import os
import stat
from pathlib import Path

import pytest

from studio import webplay
from studio.godot import QAReport, run_qa

GAME = """<!doctype html><html><head><meta name=viewport content="width=device-width"></head><body style="margin:0">
<div style="position:absolute;top:8px;left:8px;color:#fff;font:16px sans-serif">Score</div>
<canvas id=c width=540 height=960></canvas><script>
const c=document.getElementById('c'),x=c.getContext('2d');let px=270,k={},stars=[];
for(let i=0;i<20;i++)stars.push([Math.random()*540,Math.random()*960]);
addEventListener('keydown',e=>k[e.key]=1);addEventListener('keyup',e=>k[e.key]=0);
window.__studio_state=()=>({px:Math.round(px)});
function f(){if(k.ArrowRight)px+=SPEED;if(k.ArrowLeft)px-=SPEED;x.fillStyle='#246';x.fillRect(0,0,540,960);
x.fillStyle='#fff';for(const s of stars)x.fillRect(s[0],s[1],3,3);x.fillStyle='#fc3';x.fillRect(px-20,460,40,40);requestAnimationFrame(f)}f();
</script></body></html>"""


def _game(d: Path, speed=4, extra="") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(GAME.replace("SPEED", str(speed)).replace("<body style=\"margin:0\">", "<body style=\"margin:0\">" + extra))
    return d


def _fake_chrome(tmp_path, result: dict) -> str:
    """A stand-in browser: prints the harness result for --dump-dom and writes a PNG for --screenshot."""
    f = tmp_path / "chrome"
    payload = "STUDIO_RESULT" + json.dumps(result) + "END_STUDIO_RESULT"
    (tmp_path / "payload.txt").write_text(payload)
    f.write_text("#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in --screenshot=*) printf '\\x89PNG' > \"${a#--screenshot=}\";; "
                 f"--dump-dom) cat '{tmp_path / 'payload.txt'}';; esac; done\nexit 0\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


def _result(**kw):
    r = {"seed": 1337, "idle": False, "errors": [], "canvas": [540, 960], "final": {"hash": "a", "range": 90},
         "trace": [{"t": 500, "f": {"hash": "a"}}, {"t": 2000, "f": {"hash": "b"}}], "first_input": 1500, "text": [], "state": None}
    r.update(kw)
    return r


def test_entry_detection_and_godot_projects_are_not_web(tmp_path):
    assert webplay.find_entry(tmp_path) is None
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<html></html>")
    assert webplay.find_entry(tmp_path).name == "index.html" and webplay.is_web_game(tmp_path)
    (tmp_path / "project.godot").write_text("")
    assert not webplay.is_web_game(tmp_path)


def test_harness_goes_first_and_carries_the_script(tmp_path):
    page = webplay.harness_html("<html><head><title>x</title></head><body></body></html>", [{"at": 100, "key": "a"}])
    assert page.index("<script>") < page.index("<title>") and '"key": "a"' in page
    assert webplay.harness_html("<p>bare</p>", []).startswith("<script>")


def test_custom_play_script(tmp_path):
    (tmp_path / "studio_play.json").write_text(json.dumps({"steps": [{"at": 900, "tap": [0.1, 0.9]}], "budget_ms": 5000}))
    steps, budget = webplay.load_steps(tmp_path)
    assert steps == [{"at": 900, "tap": [0.1, 0.9]}] and budget == 5000
    (tmp_path / "studio_play.json").write_text("not json")
    assert webplay.load_steps(tmp_path)[0] == webplay.DEFAULT_STEPS


def test_parse_result_ignores_the_marker_in_the_script():
    dom = "<script>pre.textContent = 'STUDIO_' + 'RESULT'</script><pre>STUDIO_RESULT{&quot;a&quot;: 1}END_STUDIO_RESULT</pre>"
    assert webplay.parse_result(dom) == {"a": 1}
    assert webplay.parse_result("nothing") is None


def test_replay_diff():
    a = _result()
    assert webplay.replay_diff(a, _result())[0] is False
    changed, summary = webplay.replay_diff(a, _result(trace=[{"t": 500, "f": {"hash": "a"}}, {"t": 2000, "f": {"hash": "c"}}]))
    assert changed and "first at 2.0 s" in summary
    assert webplay.replay_diff(a, _result(state={"score": 3}))[0] is True
    assert webplay.replay_diff(None, a)[0] is False


def test_no_browser_is_a_skip_not_a_fail(tmp_path):
    rep = QAReport()
    webplay.web_checks(_game(tmp_path / "g"), None, rep)
    assert rep.passed and rep.checks[0]["status"] == "skip"


def test_fake_browser_failures_fail_qa(tmp_path):
    g = _game(tmp_path / "g")
    chrome = _fake_chrome(tmp_path, _result(errors=["Uncaught ReferenceError: x"], text=["too small (9px): \"tip\""],
                                            final={"hash": "a", "range": 0}))
    rep = QAReport()
    webplay.web_checks(g, chrome, rep, shots_dir=tmp_path / "shots")
    failed = {c["name"] for c in rep.checks if c["status"] == "fail"}
    assert "web: page opens with no errors" in failed and "web: text readable and on screen" in failed
    assert "web: game draws something" in failed and "web: responds to the scripted input" in failed  # idle == played
    assert rep.shots and not (g / webplay.HARNESS_PAGE).exists()


def test_run_qa_routes_web_games_to_the_browser(tmp_path):
    g = _game(tmp_path / "g")
    chrome = _fake_chrome(tmp_path, _result())
    rep = run_qa(g, ["index.html"], None, platform="web", chrome_bin=chrome, shots_dir=tmp_path / "s")
    names = [c["name"] for c in rep.checks]
    assert "web: page opens with no errors" in names and not any("godot" in n for n in names)
    rep2 = run_qa(g, [], None, platform="android")
    assert any("godot" in c["name"] for c in rep2.checks)


REAL = webplay.find_chrome()


@pytest.mark.skipif(not REAL or os.environ.get("STUDIO_SKIP_BROWSER") == "1", reason="no Chrome/Chromium")
def test_real_browser_play_and_deterministic_replay(tmp_path):
    main, change, same = _game(tmp_path / "main"), _game(tmp_path / "change", speed=9), _game(tmp_path / "same")
    rep = QAReport()
    webplay.web_checks(change, REAL, rep, shots_dir=tmp_path / "shots", baseline=main)
    by = {c["name"].split(":")[0] + ":" + c["name"].split(":")[1][:12] if ":" in c["name"] else c["name"]: c for c in rep.checks}
    assert rep.passed, rep.markdown()
    assert any(c["name"].startswith("seeded replay") and "frames differ" in c["name"] for c in rep.checks)
    assert any(s.endswith("shot_web_phone.png") for s in rep.shots) and by
    rep2 = QAReport()
    webplay.web_checks(same, REAL, rep2, baseline=main)
    assert any(c["name"].startswith("seeded replay") and "no visible change" in c["name"] for c in rep2.checks)


@pytest.mark.skipif(not REAL or os.environ.get("STUDIO_SKIP_BROWSER") == "1", reason="no Chrome/Chromium")
def test_real_browser_catches_a_broken_page(tmp_path):
    g = tmp_path / "bad"
    g.mkdir()
    (g / "index.html").write_text("<html><head></head><body><p style='font-size:9px'>tiny</p><canvas width=200 height=200>"
                                  "</canvas><script>document.querySelector('canvas').getContext('2d');boom();</script></body></html>")
    rep = QAReport()
    webplay.web_checks(g, REAL, rep)
    failed = {c["name"] for c in rep.checks if c["status"] == "fail"}
    assert {"web: page opens with no errors", "web: text readable and on screen", "web: game draws something"} <= failed
