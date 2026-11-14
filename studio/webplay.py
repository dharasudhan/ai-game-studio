"""Web QA (1.7.0): play a browser game headless with scripted input, and replay it with a fixed seed.

No LLM calls and no extra Python packages: a local http.server serves the game, a copy of its page gets a small
harness script, and Chrome/Chromium (headless) runs it on virtual time so the same seed gives the same frames.

Checks, for a web-platform game that has an index.html:
- opens with no errors (uncaught exceptions, failed promises, console.error)
- draws something (the main canvas is not one flat colour)
- responds to input (the scripted run ends on a different frame than an idle run with the same seed)
- text is readable and on screen (DOM text under 12 px, off-screen or overlapping)
- seeded replay: the same script on main and on the change, frame by frame, so Gate 3 shows what moved
Idea borrowed from Donchitos/Claude-Code-Game-Studios (MIT): scripted key presses in a headless browser and a
seeded replay after every feature. Code here is our own.
"""
from __future__ import annotations

import functools
import glob
import json
import os
import re
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ENTRIES = ("index.html", "web/index.html", "public/index.html", "dist/index.html", "build/web/index.html",
           "export/web/index.html")
HARNESS_PAGE = ".studio_play.html"
SCRIPT_FILE = "studio_play.json"          # optional per-game input script in the repo root
DEFAULT_SEED = 1337
DEFAULT_BUDGET_MS = 9000
PHONE = (540, 1170)
# default input script: wait for the loader, tap to start, then move, jump, confirm. ms after page load.
DEFAULT_STEPS = [
    {"at": 1500, "tap": [0.5, 0.5]},
    {"at": 2200, "key": "ArrowRight", "hold": 500},
    {"at": 2900, "key": " ", "hold": 120},
    {"at": 3400, "key": "ArrowLeft", "hold": 400},
    {"at": 4000, "key": "ArrowUp", "hold": 200},
    {"at": 4500, "tap": [0.3, 0.7]},
    {"at": 5000, "tap": [0.7, 0.7]},
    {"at": 5600, "key": "Enter", "hold": 80},
    {"at": 6200, "key": "ArrowDown", "hold": 300},
]

HARNESS_JS = r"""
(function () {
  var Q = new URLSearchParams(location.search);
  var seed = (parseInt(Q.get('studio_seed') || '1337', 10) >>> 0) || 1337;
  var idle = Q.get('studio_idle') === '1';
  var END = parseInt(Q.get('studio_end') || '8000', 10);
  var SETTLE = parseInt(Q.get('studio_settle') || '400', 10);
  var STEPS = __STEPS__;
  var a = seed;
  Math.random = function () {
    a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  // --- the harness owns the game's clock: timers, animation frames, performance.now and Date.now run on a
  // simulated clock that moves in 16 ms frames once the page has loaded, so the same seed and the same
  // input give the same frames on every run and every machine.
  var realST = window.setTimeout.bind(window);
  var fnow = 0, seq = 0, q = [], dead = {}, BASE = 1767225600000, started = false;
  function push(fn, t, args, every, raf) { var id = ++seq; q.push({ id: id, t: t, fn: fn, args: args || [], every: every, raf: raf }); return id; }
  window.setTimeout = function (fn, d) {
    if (typeof fn !== 'function') return 0;
    return push(fn, fnow + Math.max(0, +d || 0), [].slice.call(arguments, 2), 0, false);
  };
  window.setInterval = function (fn, d) {
    if (typeof fn !== 'function') return 0;
    var e = Math.max(4, +d || 0); return push(fn, fnow + e, [].slice.call(arguments, 2), e, false);
  };
  window.clearTimeout = window.clearInterval = function (id) { if (id) dead[id] = 1; };
  window.requestAnimationFrame = function (cb) { return push(cb, (Math.floor(fnow / 16) + 1) * 16, null, 0, true); };
  window.cancelAnimationFrame = function (id) { if (id) dead[id] = 1; };
  var realPerfNow = performance.now.bind(performance);
  performance.now = function () { return fnow; };
  Date.now = function () { return BASE + fnow; };
  var errors = [];
  function err(m) { if (errors.length < 20) errors.push(String(m).slice(0, 300)); }
  window.addEventListener('error', function (e) { err(e.message || (e.target && e.target.src ? 'failed to load ' + e.target.src : e)); }, true);
  window.addEventListener('unhandledrejection', function (e) { err('unhandled promise: ' + (e.reason && e.reason.message || e.reason)); });
  var ce = console.error; console.error = function () { err([].slice.call(arguments).join(' ')); return ce.apply(console, arguments); };
  var gc = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (t, o) {
    if (/webgl|experimental/.test(t)) { o = Object.assign({}, o || {}, { preserveDrawingBuffer: true }); }
    return gc.call(this, t, o);
  };
  function canvas() {
    var cs = [].slice.call(document.querySelectorAll('canvas'));
    cs.sort(function (x, y) { return y.width * y.height - x.width * x.height; });
    return cs[0] || null;
  }
  function frame() {
    var c = canvas(); if (!c || !c.width || !c.height) return null;
    try {
      var s = document.createElement('canvas'); s.width = 32; s.height = 32;
      var x = gc.call(s, '2d'); x.drawImage(c, 0, 0, 32, 32);
      var d = x.getImageData(0, 0, 32, 32).data, h = 2166136261, mn = 255, mx = 0;
      for (var i = 0; i < d.length; i += 4) {
        var v = (d[i] + d[i + 1] + d[i + 2]) / 3 | 0; if (v < mn) mn = v; if (v > mx) mx = v;
        h = Math.imul(h ^ (v >> 2), 16777619) >>> 0;
      }
      return { hash: h.toString(16), range: mx - mn };
    } catch (e) { return { hash: 'unreadable', range: -1 }; }
  }
  var CODES = { ' ': 'Space', 'Enter': 'Enter', 'Escape': 'Escape' };
  function code(k) { return CODES[k] || (k.length === 1 ? 'Key' + k.toUpperCase() : k); }
  var KC = { ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, ' ': 32, Enter: 13, Escape: 27 };
  function target() { var c = canvas(); return (document.activeElement && document.activeElement !== document.body) ? document.activeElement : (c || document.body); }
  function key(type, k) {
    target().dispatchEvent(new KeyboardEvent(type, { key: k, code: code(k), keyCode: KC[k] || k.toUpperCase().charCodeAt(0),
      which: KC[k] || 0, bubbles: true, cancelable: true }));
  }
  function tap(fx, fy, t) {
    var c = canvas(), r = c ? c.getBoundingClientRect() : { left: 0, top: 0, width: innerWidth, height: innerHeight };
    var x = r.left + r.width * fx, y = r.top + r.height * fy, el = document.elementFromPoint(x, y) || c || document.body;
    var o = { clientX: x, clientY: y, bubbles: true, cancelable: true, pointerId: 1, pointerType: 'touch', isPrimary: true, button: 0, buttons: 1 };
    el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new MouseEvent('mousedown', o));
    push(function () {
      o.buttons = 0;
      el.dispatchEvent(new PointerEvent('pointerup', o)); el.dispatchEvent(new MouseEvent('mouseup', o));
      el.dispatchEvent(new MouseEvent('click', o));
    }, t + 60, null, 0, false);
  }
  function textIssues() {
    var out = [], els = [], W = innerWidth, H = innerHeight;
    [].slice.call(document.body ? document.body.querySelectorAll('*') : []).forEach(function (el) {
      if (el.id === '__studio_result' || /^(SCRIPT|STYLE|NOSCRIPT|CANVAS)$/.test(el.tagName)) return;
      var own = [].slice.call(el.childNodes).some(function (n) { return n.nodeType === 3 && n.textContent.trim(); });
      if (!own) return;
      var cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
      var r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
      var label = (el.textContent || '').trim().slice(0, 40);
      if (parseFloat(cs.fontSize) < 12) out.push('too small (' + cs.fontSize + '): "' + label + '"');
      if (r.right > W + 2 || r.bottom > H + 2 || r.left < -2 || r.top < -2) out.push('off screen: "' + label + '"');
      els.push({ r: r, el: el, label: label });
    });
    for (var i = 0; i < els.length; i++) for (var j = i + 1; j < els.length; j++) {
      var p = els[i], o = els[j]; if (p.el.contains(o.el) || o.el.contains(p.el)) continue;
      var ox = Math.min(p.r.right, o.r.right) - Math.max(p.r.left, o.r.left), oy = Math.min(p.r.bottom, o.r.bottom) - Math.max(p.r.top, o.r.top);
      if (ox > 4 && oy > 4) out.push('overlap: "' + p.label + '" / "' + o.label + '"');
    }
    return out.slice(0, 20);
  }
  var trace = [], firstInput = null, T0 = 0;
  function finish() {
    var c = canvas(), res = { seed: seed, idle: idle, errors: errors, canvas: c ? [c.width, c.height] : null, final: frame(),
      trace: trace, first_input: idle ? null : firstInput, text: textIssues(), state: null };
    try { if (window.__studio_state) res.state = JSON.parse(JSON.stringify(window.__studio_state())); } catch (e) { err('__studio_state: ' + e); }
    var pre = document.createElement('pre'); pre.id = '__studio_result'; pre.style.display = 'none';
    pre.textContent = 'STUDIO_' + 'RESULT' + JSON.stringify(res) + 'END_STUDIO_' + 'RESULT';
    (document.body || document.documentElement).appendChild(pre);
  }
  // run what is due up to time `to`, in time order (ties: the order they were set)
  function runTo(to) {
    for (;;) {
      var best = null;
      for (var i = 0; i < q.length; i++) { var it = q[i]; if (dead[it.id]) continue; if (it.t <= to && (!best || it.t < best.t || (it.t === best.t && it.id < best.id))) best = it; }
      if (!best) break;
      fnow = best.t;
      if (best.every) { var n = { id: best.id, t: best.t + best.every, fn: best.fn, args: best.args, every: best.every }; q.push(n); }
      q.splice(q.indexOf(best), 1);
      try { best.fn.apply(window, best.raf ? [fnow] : best.args); } catch (e) { err((e && e.message) || e); }
    }
    fnow = to;
    q = q.filter(function (x) { return !dead[x.id]; });
  }
  var ch = new MessageChannel(), tick = 0;
  ch.port1.onmessage = function () {
    tick += 16; runTo(T0 + tick);
    if (tick >= END) { finish(); return; }
    ch.port2.postMessage(0);
  };
  function start() {
    if (started) return; started = true;
    T0 = fnow;
    for (var t = 500; t < END; t += 500) (function (t) { push(function () { trace.push({ t: t, f: frame() }); }, T0 + t, null, 0, false); })(t);
    if (!idle) STEPS.forEach(function (s) {
      if (firstInput === null || s.at < firstInput) firstInput = s.at;
      push(function () {
        if (s.tap) tap(s.tap[0], s.tap[1], T0 + s.at);
        if (s.key) { key('keydown', s.key); push(function () { key('keyup', s.key); }, T0 + s.at + (s.hold || 100), null, 0, false); }
      }, T0 + s.at, null, 0, false);
    });
    ch.port2.postMessage(0);
  }
  // let the page load and its loaders settle on the real clock, then hand over to the simulated one
  window.addEventListener('load', function () { realST(start, SETTLE); });
  realST(start, 6000);
})();
"""


def find_entry(wt: Path) -> Path | None:
    for rel in ENTRIES:
        p = Path(wt) / rel
        if p.is_file():
            return p
    return None


def is_web_game(wt: Path) -> bool:
    """A web game we can play in the browser: has a page and is not a Godot project (Godot QA covers those)."""
    return find_entry(wt) is not None and not (Path(wt) / "project.godot").exists()


def find_chrome(configured: str = "") -> str | None:
    for c in (configured, os.environ.get("CHROME_BIN", "")):
        if c and (shutil.which(c) or Path(c).exists()):
            return shutil.which(c) or c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                 "chrome-headless-shell", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    mac = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium",
           "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for p in mac + sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium*/*/chrome*"))):
        if Path(p).is_file() and os.access(p, os.X_OK):
            return p
    return None


def load_steps(wt: Path) -> tuple[list[dict], int]:
    """The game's own studio_play.json ({"steps": [...], "budget_ms": 9000}) or the default script."""
    f = Path(wt) / SCRIPT_FILE
    if f.is_file():
        try:
            d = json.loads(f.read_text())
            steps = [s for s in d.get("steps", []) if isinstance(s, dict) and isinstance(s.get("at"), (int, float))]
            if steps:
                return steps, int(d.get("budget_ms") or DEFAULT_BUDGET_MS)
        except (ValueError, TypeError, AttributeError):
            pass
    return list(DEFAULT_STEPS), DEFAULT_BUDGET_MS


def harness_html(page: str, steps: list[dict]) -> str:
    js = HARNESS_JS.replace("__STEPS__", json.dumps(steps))
    tag = "<script>" + js + "</script>"
    m = re.search(r"<head[^>]*>", page, re.I)
    if m:
        return page[:m.end()] + tag + page[m.end():]
    m = re.search(r"<html[^>]*>", page, re.I)
    if m:
        return page[:m.end()] + "<head>" + tag + "</head>" + page[m.end():]
    return tag + page


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 - keep test/QA output clean
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server:
    """Serves one folder on 127.0.0.1 (ES modules and fetch() don't work from file://)."""

    def __init__(self, root: Path):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(root)))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _chrome(chrome: str, url: str, budget_ms: int, timeout: int, screenshot: Path | None = None,
            size: tuple[int, int] = PHONE) -> tuple[int, str]:
    cmd = [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--mute-audio",
           "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--use-gl=swiftshader",
           "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required",
           f"--window-size={size[0]},{size[1]}", "--virtual-time-budget=20000", "--run-all-compositor-stages-before-draw"]
    cmd += [f"--screenshot={screenshot}"] if screenshot else ["--dump-dom"]
    try:
        p = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + "\n" + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"timeout after {timeout}s {e.stdout or ''}"
    except OSError as e:
        return 127, str(e)


def parse_result(out: str) -> dict | None:
    found = re.findall(r"STUDIO_RESULT(\{.*?\})END_STUDIO_RESULT", out, re.S)
    if not found:
        return None
    raw = found[-1].replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    try:
        return json.loads(raw)
    except ValueError:
        return None


def run_game(wt: Path, chrome: str, seed: int = DEFAULT_SEED, idle: bool = False, screenshot: Path | None = None,
             steps: list[dict] | None = None, budget_ms: int | None = None, timeout: int = 90) -> tuple[dict | None, str]:
    """One headless run of the game. Returns (harness result or None, raw output)."""
    wt = Path(wt)
    entry = find_entry(wt)
    if not entry:
        return None, "no index.html"
    if steps is None:
        steps, b = load_steps(wt)
        budget_ms = budget_ms or b
    budget_ms = budget_ms or DEFAULT_BUDGET_MS
    page = entry.parent / HARNESS_PAGE
    page.write_text(harness_html(entry.read_text(errors="ignore"), steps))
    try:
        with Server(entry.parent) as srv:
            url = (f"http://127.0.0.1:{srv.port}/{HARNESS_PAGE}?studio_seed={seed}&studio_end={budget_ms}"
                   + ("&studio_idle=1" if idle else ""))
            code, out = _chrome(chrome, url, budget_ms, timeout)
            res = parse_result(out)
            if screenshot is not None:
                Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
                _chrome(chrome, url, budget_ms, timeout, screenshot=Path(screenshot))
    finally:
        page.unlink(missing_ok=True)
    return res, out


def replay_diff(base: dict | None, new: dict | None) -> tuple[bool, str]:
    """Compare two seeded runs frame by frame. Returns (changed, one-line summary)."""
    if not base or not new:
        return False, "replay not compared (a run gave no result)"
    bt = {x["t"]: (x.get("f") or {}).get("hash") for x in base.get("trace", [])}
    nt = {x["t"]: (x.get("f") or {}).get("hash") for x in new.get("trace", [])}
    moved = [t for t in sorted(set(bt) | set(nt)) if bt.get(t) != nt.get(t)]
    state_changed = base.get("state") != new.get("state")
    if not moved and not state_changed:
        return False, "no visible change from main with the same seed and input"
    parts = []
    if moved:
        parts.append(f"{len(moved)} of {len(set(bt) | set(nt))} frames differ from main, first at {moved[0] / 1000:.1f} s")
    if state_changed:
        parts.append("game state at the end differs (__studio_state)")
    return True, "; ".join(parts)


def web_checks(wt: Path, chrome: str | None, rep, shots_dir: Path | None = None, baseline: Path | None = None,
               replay: bool = True) -> None:
    """Adds the web play checks (and the seeded replay vs main) to a QAReport."""
    if not chrome:
        rep.add("web: headless play check", None, "Chrome/Chromium not found; install Google Chrome or set chrome_bin in Settings")
        return
    shot = (Path(shots_dir) / "shot_web_phone.png") if shots_dir is not None else None
    if shots_dir is not None:
        Path(shots_dir).mkdir(parents=True, exist_ok=True)
        for old in Path(shots_dir).glob("shot_web_*.png"):
            old.unlink()
    res, out = run_game(wt, chrome, screenshot=shot)
    if res is None:
        rep.add("web: page opens and the play script runs", False, "no result from the page (it crashed or never loaded)\n" + out[-1500:])
        return
    errs = res.get("errors") or []
    rep.add("web: page opens with no errors", not errs, "\n".join(errs))
    fin = res.get("final") or {}
    if not res.get("canvas"):
        rep.add("web: game draws a canvas", None, "no <canvas> on the page")
    elif fin.get("range", 0) < 0:
        rep.add("web: game draws something", None, "canvas could not be read")
    else:
        rep.add("web: game draws something", fin.get("range", 0) >= 8, "the canvas is one flat colour at the end of the run")
    idle, _ = run_game(wt, chrome, idle=True)
    if idle and res.get("first_input") is not None:
        after = [x["t"] for x in res.get("trace", []) if x["t"] > res["first_input"]]
        it = {x["t"]: (x.get("f") or {}).get("hash") for x in idle.get("trace", [])}
        pt = {x["t"]: (x.get("f") or {}).get("hash") for x in res.get("trace", [])}
        responds = any(pt.get(t) != it.get(t) for t in after) or res.get("state") != idle.get("state")
        rep.add("web: responds to the scripted input", responds,
                "the frames with input match an idle run with the same seed: taps and keys do nothing")
    text = res.get("text") or []
    rep.add("web: text readable and on screen", not text, "\n".join(text))
    if shot is not None:
        files = [str(shot)] if shot.exists() else []
        rep.shots = (rep.shots or []) + files
        rep.add(f"seen-it: game played in a headless browser, {len(files)} screenshot(s) saved", bool(files),
                "no screenshot saved" if not files else "")
    if replay and baseline is not None and is_web_game(baseline):
        steps, budget = load_steps(wt)
        bshot = (Path(shots_dir) / "shot_web_main.png") if shots_dir is not None else None
        base, _ = run_game(baseline, chrome, steps=steps, budget_ms=budget, screenshot=bshot)
        changed, summary = replay_diff(base, res)
        if changed and bshot is not None and bshot.exists():
            rep.shots = (rep.shots or []) + [str(bshot)]
            summary += " (main's last frame is shot_web_main.png)"
        rep.add(f"seeded replay vs main (seed {DEFAULT_SEED}): {summary}", True, "")
