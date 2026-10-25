"""Pluggable AI engines.

Every adapter implements `run(req) -> EngineResult`. Adapters that can edit files in `req.cwd`
themselves (CLI agents) set `agentic = True`; the others return file blocks in their JSON reply,
which the studio writes for them. Errors are classified so the worker can back off correctly:

* RateLimited       -> retry later with a long backoff (quota / 429 / RESOURCE_EXHAUSTED)
* EngineUnavailable -> pause the queue, do not burn an attempt (binary missing, login needed)
* EngineError       -> ordinary failure, retry with exponential backoff
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


class EngineError(Exception):
    pass


class RateLimited(EngineError):
    pass


class EngineUnavailable(EngineError):
    pass


@dataclass
class EngineRequest:
    prompt: str
    cwd: Path
    role: str
    task: str
    edit: bool = False          # True when the agent is expected to change files in cwd
    timeout: int = 900


@dataclass
class EngineResult:
    text: str
    tokens: int = 0
    model: str = ""
    raw: dict = field(default_factory=dict)


class Engine(Protocol):
    name: str
    agentic: bool

    def run(self, req: EngineRequest) -> EngineResult: ...


_RATE_PAT = re.compile(r"(429|rate.?limit|quota|resource_exhausted|too many requests|credits? (exhausted|remaining: 0)|usage limit)", re.I)
_AUTH_PAT = re.compile(r"(authentication required|not authenticated|login required|please (log|sign) ?in|unauthenticated|auth.*expired)", re.I)


def classify(msg: str) -> EngineError:
    if _RATE_PAT.search(msg or ""):
        return RateLimited(msg[:2000])
    if _AUTH_PAT.search(msg or ""):
        return EngineUnavailable("Engine needs sign-in: " + msg[:1500])
    return EngineError(msg[:2000])


def _last_json_obj(stdout: str) -> dict | None:
    s = stdout.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for line in reversed(s.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _run_cli(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise EngineUnavailable(f"'{cmd[0]}' not found. Run setup.sh or set its path in Settings.") from e
    except subprocess.TimeoutExpired as e:
        raise EngineError(f"engine timed out after {timeout}s") from e


# ---------------------------------------------------------------------------
class AntigravityCLIEngine:
    """Google Antigravity CLI (`agy`) in headless print mode, signed in with the user's Google account.

    Since 2026-06-18 Google AI Pro/Ultra usage goes through Antigravity CLI (Gemini CLI's "Login with
    Google" stopped serving those tiers). Flags per https://antigravity.google/docs/cli/headless :
    `agy -p <prompt> --output-format json [--model slug] [--effort lvl] [--print-timeout 15m]
    [--dangerously-skip-permissions]`. File reads/writes inside the working directory are auto-allowed
    in headless mode; shell commands are soft-denied unless allowed in settings or skip-permissions.
    """
    name = "agy"
    agentic = True

    def __init__(self, bin: str = "agy", model: str = "", effort: str = "", skip_permissions: bool = False):
        self.bin, self.model, self.effort, self.skip = bin or "agy", model, effort, skip_permissions

    def command(self, req: EngineRequest) -> list[str]:
        cmd = [self.bin, "-p", req.prompt, "--output-format", "json", "--print-timeout", f"{max(60, req.timeout)}s"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        if req.edit and self.skip:
            cmd += ["--dangerously-skip-permissions"]
        return cmd

    def run(self, req: EngineRequest) -> EngineResult:
        p = _run_cli(self.command(req), req.cwd, req.timeout + 60)
        data = _last_json_obj(p.stdout)
        if data is None:
            raise classify((p.stderr or "") + (p.stdout or "") or f"no output (exit {p.returncode})")
        if data.get("status") != "SUCCESS" or p.returncode != 0:
            raise classify(f"{data.get('status')}: {data.get('error') or p.stderr}")
        usage = data.get("usage") or {}
        return EngineResult(text=data.get("response", ""), tokens=int(usage.get("total_tokens") or 0),
                            model=self.model or "agy-default", raw={"conversation_id": data.get("conversation_id")})


class GeminiCLIEngine:
    """Legacy Gemini CLI (npm @google/gemini-cli): `gemini -p ... -o json --approval-mode auto_edit -m model`.

    Note: for Google AI Pro personal accounts, Login-with-Google stopped working on 2026-06-18; this
    adapter still works with GEMINI_API_KEY / Vertex / Code Assist Standard-Enterprise auth.
    """
    name = "gemini_cli"
    agentic = True

    def __init__(self, bin: str = "gemini", model: str = ""):
        self.bin, self.model = bin or "gemini", model

    def command(self, req: EngineRequest) -> list[str]:
        cmd = [self.bin, "-p", req.prompt, "--output-format", "json",
               "--approval-mode", "auto_edit" if req.edit else "default"]
        if self.model:
            cmd += ["-m", self.model]
        return cmd

    def run(self, req: EngineRequest) -> EngineResult:
        p = _run_cli(self.command(req), req.cwd, req.timeout)
        data = _last_json_obj(p.stdout)
        if data is None or p.returncode != 0 or data.get("error"):
            err = (data or {}).get("error")
            raise classify(json.dumps(err) if err else (p.stderr or p.stdout or f"exit {p.returncode}"))
        tokens = 0
        for m in ((data.get("stats") or {}).get("models") or {}).values():
            tokens += int(((m or {}).get("tokens") or {}).get("total") or 0)
        return EngineResult(text=data.get("response", ""), tokens=tokens, model=self.model or "gemini-default")


class GenAIEngine:
    """Gemini API via the google-genai SDK and GEMINI_API_KEY. Not agentic: returns file blocks."""
    name = "genai"
    agentic = False

    def __init__(self, model: str = "gemini-flash-latest", api_key: str | None = None):
        self.model = model or "gemini-flash-latest"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def run(self, req: EngineRequest) -> EngineResult:
        if not self.api_key:
            raise EngineUnavailable("GEMINI_API_KEY is not set (put it in .env)")
        try:
            from google import genai  # type: ignore
        except ImportError as e:
            raise EngineUnavailable("google-genai not installed: pip install google-genai") from e
        try:
            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(model=self.model, contents=req.prompt)
        except Exception as e:  # SDK raises google.genai.errors.APIError subclasses
            code = getattr(e, "code", None)
            if code == 429:
                raise RateLimited(str(e)) from e
            if code in (401, 403):
                raise EngineUnavailable(str(e)) from e
            raise classify(str(e)) from e
        um = getattr(resp, "usage_metadata", None)
        return EngineResult(text=resp.text or "", tokens=int(getattr(um, "total_token_count", 0) or 0), model=self.model)


class OllamaEngine:
    """Local Ollama for cheap chores (keep to small models on 16 GB: 3B-8B). Not agentic."""
    name = "ollama"
    agentic = False

    def __init__(self, host: str = "http://127.0.0.1:11434", model: str = "llama3.2:3b"):
        self.host, self.model = host.rstrip("/"), model

    def run(self, req: EngineRequest) -> EngineResult:
        body = json.dumps({"model": self.model, "prompt": req.prompt, "stream": False}).encode()
        r = urllib.request.Request(self.host + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=req.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            raise EngineUnavailable(f"Ollama not reachable at {self.host}: {e}") from e
        return EngineResult(text=data.get("response", ""), model=self.model,
                            tokens=int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0)))


# ---------------------------------------------------------------------------
FakeHandler = Callable[[EngineRequest], "str | EngineResult | Exception"]


class FakeEngine:
    """Deterministic engine for tests and offline demos.

    Default behaviour returns a valid reply for each task. Tests can push one-off behaviours with
    `script(task, handler_or_text_or_exception)`; queued entries for a task are consumed in order.
    When `agentic` is True the fake engineer writes files directly into cwd like a CLI agent would.
    """
    name = "fake"

    def __init__(self, agentic: bool = True):
        self.agentic = agentic
        self.calls: list[EngineRequest] = []
        self._scripts: dict[str, list] = {}

    def script(self, task: str, item) -> None:
        self._scripts.setdefault(task, []).append(item)

    def run(self, req: EngineRequest) -> EngineResult:
        self.calls.append(req)
        q = self._scripts.get(req.task)
        if q:
            item = q.pop(0)
            if isinstance(item, Exception):
                raise item
            if callable(item):
                item = item(req)
            if isinstance(item, EngineResult):
                return item
            return EngineResult(text=str(item), tokens=1, model="fake")
        return EngineResult(text=self._default(req), tokens=1, model="fake")

    def _default(self, req: EngineRequest) -> str:
        t = req.task
        m = re.search(r"^TICKET #(\d+): (.*)$", req.prompt, re.M)
        tid, ttitle = (m.group(1), m.group(2)) if m else ("0", "work")
        if t == "designer.pitch":
            out = {"title": "Orbit Hopper", "logline": "Hop between orbiting planets; one tap, endless runs.",
                   "pitch_markdown": "# Orbit Hopper\n\n## Hook\nOne-tap orbital jumps.\n\n## Monetization\nRewarded ads + remove-ads IAP."}
        elif t == "producer.plan":
            out = {"milestones": [{"title": "M1 Core loop", "goal": "Playable hop on device",
                                   "tickets": [{"agent": "engineer", "title": "Player hop mechanic",
                                                "description": "Tap to jump between two orbits."}]}]}
        elif t == "ticket.work":
            slug = f"t{tid}"
            files = [
                {"path": f"scripts/feature_{slug}.gd",
                 "content": f"extends RefCounted\n## {ttitle}\n\nfunc value() -> int:\n\treturn 42\n"},
                {"path": f"tests/test_feature_{slug}.gd",
                 "content": f"extends RefCounted\n\nfunc test_value() -> bool:\n\treturn load(\"res://scripts/feature_{slug}.gd\").new().value() == 42\n"},
            ]
            if self.agentic:
                for f in files:
                    p = Path(req.cwd) / f["path"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(f["content"])
                out = {"summary": f"Implemented {ttitle}", "files": []}
            else:
                out = {"summary": f"Implemented {ttitle}", "files": files}
        elif t == "qa.review":
            out = {"verdict": "pass", "summary": "Looks good.", "bugs": []}
        elif t == "producer.standup":
            out = {"standup_markdown": "## Standup\n- All on track."}
        elif t == "marketing.release_kit":
            out = {"store_listing_markdown": "# Orbit Hopper\nShort and full description.",
                   "screenshots_plan_markdown": "1. Title\n2. Gameplay", "trailer_script_markdown": "0-5s hook",
                   "public_actions": [{"channel": "x", "content": "Orbit Hopper is coming soon!"}]}
        elif t == "marketing.public_redraft":
            out = {"public_actions": [{"channel": "x", "content": "Orbit Hopper launches this week."}]}
        elif t in ("support.triage", "support.fixed_replies"):
            from .support import default_reply, rule_classify
            items = _marked_json(req.prompt, "FEEDBACK_ITEMS")
            if t == "support.triage":
                res = []
                for it in items:
                    c = rule_classify(it.get("text", ""), it.get("rating"), it.get("type_hint", ""))
                    reply = default_reply(it, c, it.get("game") or "the game")
                    res.append({"id": it["id"], **c, "summary": (it.get("text", "")[:80]).replace("\n", " "),
                                "group_label": c["category"], "needs_reply": reply is not None, "reply_draft": reply or ""})
                out = {"items": res}
            else:
                ver = (re.search(r"^Fixed in version: (.*)$", req.prompt, re.M) or [None, "the latest update"])[1]
                out = {"replies": [{"id": it["id"], "reply_draft": f"Good news: this is fixed in v{ver}. Please update and tell us if it still happens. Thanks for reporting it!"} for it in items]}
        elif t == "support.redraft_reply":
            out = {"reply_draft": "Thanks for your patience - we have fixed this and an update is on its way."}
        elif t == "bugfix.intake":
            out = {"title": "Crash when the level loads", "severity": "high",
                   "repro_steps": "1. Install the latest build\n2. Start level 3\n3. Game closes", "expected": "Level loads",
                   "actual": "Game crashes", "suspected_area": "scripts/main.gd", "test_plan": "Load the level script headless and assert it returns a node"}
        elif t == "bugfix.fix":
            files = [
                {"path": f"scripts/bugfix_t{tid}.gd", "content": "extends RefCounted\n\nfunc safe_level(i: int) -> int:\n\treturn clampi(i, 0, 9)\n"},
                {"path": f"tests/test_bug_t{tid}.gd", "content": f"extends RefCounted\n\nfunc test_level_index_clamped() -> bool:\n\treturn load(\"res://scripts/bugfix_t{tid}.gd\").new().safe_level(99) == 9\n"},
            ]
            if self.agentic:
                for f in files:
                    p = Path(req.cwd) / f["path"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(f["content"])
                files = []
            out = {"summary": f"Fixed {ttitle}", "root_cause": "level index out of range", "regression_test": f"tests/test_bug_t{tid}.gd",
                   "no_test_reason": "", "files": files}
        elif t == "analyst.analyze":
            out = {"report_markdown": "## Findings\n- Crash on level 3.",
                   "proposed_milestone": {"title": "Fix crashes", "goal": "0 crashes",
                                          "tickets": [{"agent": "engineer", "title": "Fix level 3 crash", "description": "null ref"}]}}
        else:
            out = {"summary": "ok"}
        return "```json\n" + json.dumps(out, indent=1) + "\n```"


def _marked_json(prompt: str, name: str) -> list:
    m = re.search(rf"<<<{name}\n(.*?)\n{name}>>>", prompt, re.S)
    try:
        return json.loads(m.group(1)) if m else []
    except json.JSONDecodeError:
        return []


def build_engine(name: str, s: dict[str, str], fake: FakeEngine | None = None) -> Engine:
    name = (name or "agy").strip()
    if name == "agy":
        return AntigravityCLIEngine(s.get("agy_bin", "agy"), s.get("agy_model", ""), s.get("agy_effort", ""),
                                    s.get("agy_skip_permissions") == "1")
    if name == "gemini_cli":
        return GeminiCLIEngine(s.get("gemini_bin", "gemini"), s.get("gemini_model", ""))
    if name == "genai":
        return GenAIEngine(s.get("genai_model", "gemini-flash-latest"))
    if name == "ollama":
        return OllamaEngine(s.get("ollama_host", "http://127.0.0.1:11434"), s.get("ollama_model", "llama3.2:3b"))
    if name == "fake":
        return fake or FakeEngine()
    raise EngineUnavailable(f"unknown engine '{name}'")


def which(binary: str) -> str | None:
    return shutil.which(binary) if binary else None
