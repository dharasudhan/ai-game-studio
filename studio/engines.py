"""Pluggable model providers ("engines").

Every provider implements the same small interface:

    run(req: EngineRequest) -> EngineResult      one agent turn
    test(deep=False) -> dict                     "Test connection" for the setup wizard / Settings
    name, agentic, model                         attributes

CLI agents (Antigravity `agy`, Claude Code `claude`, Codex `codex`, Gemini CLI) edit files in `req.cwd` themselves
(`agentic = True`). API and local providers are not agentic: they return file blocks in their JSON reply and the
studio writes them (with path checks). Each agent role can use a different provider + model (Agents page or the
setup wizard). Errors are classified so the worker backs off correctly:

* RateLimited       -> retry later with a long backoff (quota / 429 / RESOURCE_EXHAUSTED)
* EngineUnavailable -> pause the queue, do not burn an attempt (binary missing, login/key missing, server down)
* EngineError       -> ordinary failure, retry with exponential backoff

Design notes (prior art studied, no code copied; see CREDITS.md): LiteLLM and aisuite route `provider:model`
strings to thin per-provider adapters behind one OpenAI-shaped interface; simonw/llm keeps keys out of config
(env var or a key store) and lets plugins add providers. We keep the same shape with zero extra dependencies
(urllib only), because the studio needs only one call type: prompt in, text + token count out.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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
    cost_usd: float | None = None


class Engine(Protocol):
    name: str
    agentic: bool

    def run(self, req: EngineRequest) -> EngineResult: ...


_RATE_PAT = re.compile(r"(429|rate.?limit|quota|resource_exhausted|too many requests|credits? (exhausted|remaining: 0)|usage limit|overloaded)", re.I)
_AUTH_PAT = re.compile(r"(authentication required|not authenticated|login required|please (log|sign) ?in|unauthenticated|auth.*expired|invalid (x-)?api.?key|api key not valid|incorrect api key|permission denied|401|403)", re.I)


def classify(msg: str) -> EngineError:
    if _RATE_PAT.search(msg or ""):
        return RateLimited(msg[:2000])
    if _AUTH_PAT.search(msg or ""):
        return EngineUnavailable("Engine needs sign-in or a valid key: " + msg[:1500])
    return EngineError(msg[:2000])


def _last_json_obj(stdout: str) -> dict | None:
    s = stdout.strip()
    if not s:
        return None
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else None
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
        raise EngineUnavailable(f"'{cmd[0]}' not found. Install it (docs/SETUP_MODELS.md) or set its path in Settings.") from e
    except subprocess.TimeoutExpired as e:
        raise EngineError(f"engine timed out after {timeout}s") from e


def _which(binary: str) -> str | None:
    if not binary:
        return None
    if os.path.sep in binary:
        return binary if os.path.exists(binary) else None
    found = shutil.which(binary)
    if found:
        return found
    for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.claude/local", "~/.npm-global/bin"):
        p = os.path.expanduser(os.path.join(d, binary))
        if os.path.exists(p):
            return p
    return None


def which(binary: str) -> str | None:
    return _which(binary)


def _ok(detail: str, **kw) -> dict:
    return {"ok": True, "detail": detail, **kw}


def _fail(detail: str, fix: str = "", **kw) -> dict:
    return {"ok": False, "detail": detail[:600], "fix": fix, **kw}


class _CLIBase:
    """Shared bits for CLI agents: binary lookup and a `--version` connection test."""
    name = "cli"
    agentic = True
    bin = ""
    model = ""
    install_hint = ""

    def version(self) -> tuple[bool, str]:
        path = _which(self.bin)
        if not path:
            return False, f"'{self.bin}' not found on PATH"
        try:
            p = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"{self.bin} --version failed: {e}"
        out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        return p.returncode == 0, (out[0] if out else f"exit {p.returncode}")[:200]

    def test(self, deep: bool = False) -> dict:
        t0 = time.time()
        ok, ver = self.version()
        if not ok:
            return _fail(ver, self.install_hint)
        if not deep:
            return _ok(f"{ver} (binary found; use 'Deep test' to send one tiny prompt)", version=ver)
        try:
            with tempfile.TemporaryDirectory() as d:
                r = self.run(EngineRequest(prompt="Reply with the single word OK.", cwd=Path(d), role="setup",
                                           task="setup.test", edit=False, timeout=120))
        except EngineError as e:
            return _fail(f"{type(e).__name__}: {e}", self.install_hint, version=ver)
        return _ok(f"{ver}: replied '{r.text.strip()[:40]}' ({r.tokens} tokens)", version=ver,
                   latency_ms=int((time.time() - t0) * 1000))


# ---------------------------------------------------------------------------  CLI agents
class AntigravityCLIEngine(_CLIBase):
    """Google Antigravity CLI (`agy`) in headless print mode, signed in with the user's Google account.

    Since 2026-06-18 Google AI Pro/Ultra usage goes through Antigravity CLI (Gemini CLI's "Login with
    Google" stopped serving those tiers). Flags per https://antigravity.google/docs/cli/headless (checked
    2026-10-28): `agy -p <prompt> --output-format json` returns one JSON envelope
    {conversation_id, status, response, duration_seconds, num_turns, usage{..., total_tokens}}.
    """
    name = "agy"
    agentic = True
    install_hint = "Install Antigravity CLI and run `agy` once to sign in with your Google AI Pro account (docs/SETUP_MODELS.md, section 1)."

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


class GeminiCLIEngine(_CLIBase):
    """Legacy Gemini CLI (npm @google/gemini-cli): `gemini -p ... -o json --approval-mode auto_edit -m model`.

    For Google AI Pro personal accounts, Login-with-Google stopped working on 2026-06-18; this adapter still
    works with GEMINI_API_KEY / Vertex / Code Assist Standard-Enterprise auth.
    """
    name = "gemini_cli"
    agentic = True
    install_hint = "npm install -g @google/gemini-cli (needs GEMINI_API_KEY for personal accounts since 2026-06-18)."

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


class ClaudeCodeCLIEngine(_CLIBase):
    """Anthropic Claude Code CLI in headless mode (https://code.claude.com/docs/en/headless, checked 2026-10-28):
    `claude -p <prompt> --output-format json [--model m] [--permission-mode acceptEdits]`. The JSON envelope has
    `result`, `is_error`, `usage` and `total_cost_usd` (a client-side estimate).

    Auth: the Claude subscription login made by running `claude` once, or ANTHROPIC_API_KEY. If ANTHROPIC_API_KEY
    is in the environment Claude Code bills the API instead of the subscription, so the studio removes it from the
    child process unless `claude_use_api_key=1`.
    """
    name = "claude_code"
    agentic = True
    install_hint = "curl -fsSL https://claude.ai/install.sh | bash  (or brew install --cask claude-code), then run `claude` once to sign in."

    def __init__(self, bin: str = "claude", model: str = "", permission_mode: str = "acceptEdits",
                 api_key: str | None = None, use_api_key: bool = False):
        self.bin, self.model, self.permission_mode = bin or "claude", model, permission_mode or "acceptEdits"
        self.api_key, self.use_api_key = api_key, use_api_key

    def command(self, req: EngineRequest) -> list[str]:
        cmd = [self.bin, "-p", req.prompt, "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if req.edit:
            cmd += ["--permission-mode", self.permission_mode]
        else:
            cmd += ["--allowedTools", "Read"]
        return cmd

    def env(self) -> dict:
        env = dict(os.environ)
        if self.use_api_key and self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        elif not self.use_api_key:
            env.pop("ANTHROPIC_API_KEY", None)
        return env

    def run(self, req: EngineRequest) -> EngineResult:
        p = _run_cli(self.command(req), req.cwd, req.timeout, env=self.env())
        data = _last_json_obj(p.stdout)
        if data is None:
            raise classify((p.stderr or "") + (p.stdout or "") or f"no output (exit {p.returncode})")
        if data.get("is_error") or p.returncode != 0 or data.get("subtype", "success") not in ("success", ""):
            raise classify(str(data.get("result") or data.get("error") or p.stderr or data.get("subtype")))
        u = data.get("usage") or {}
        tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))
        return EngineResult(text=str(data.get("result") or ""), tokens=tokens, model=self.model or "claude-default",
                            raw={"session_id": data.get("session_id")}, cost_usd=data.get("total_cost_usd"))


class CodexCLIEngine(_CLIBase):
    """OpenAI Codex CLI non-interactive mode (https://developers.openai.com/codex/noninteractive, checked
    2026-10-28): `codex exec --json --sandbox workspace-write|read-only -o <file> [-m model] <prompt>`.
    stdout is a JSONL event stream; `turn.completed` carries usage; `-o` writes the final message to a file.
    Auth: `codex login` (Sign in with ChatGPT) or an API key (`codex login --with-api-key`, CODEX_API_KEY).
    """
    name = "codex"
    agentic = True
    install_hint = "brew install --cask codex  (or npm install -g @openai/codex), then run `codex` once to sign in."

    def __init__(self, bin: str = "codex", model: str = "", api_key: str | None = None):
        self.bin, self.model, self.api_key = bin or "codex", model, api_key

    def command(self, req: EngineRequest, out_file: str) -> list[str]:
        cmd = [self.bin, "exec", "--json", "--skip-git-repo-check",
               "--sandbox", "workspace-write" if req.edit else "read-only", "-o", out_file]
        if self.model:
            cmd += ["-m", self.model]
        return cmd + [req.prompt]

    def run(self, req: EngineRequest) -> EngineResult:
        env = dict(os.environ)
        if self.api_key and not env.get("CODEX_API_KEY"):
            env["CODEX_API_KEY"] = self.api_key
        with tempfile.TemporaryDirectory() as d:
            out_file = os.path.join(d, "last.txt")
            p = _run_cli(self.command(req, out_file), req.cwd, req.timeout, env=env)
            final = Path(out_file).read_text() if os.path.exists(out_file) else ""
        tokens, errors, last_msg = 0, [], ""
        for line in (p.stdout or "").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type", "")
            if t == "turn.completed":
                u = ev.get("usage") or {}
                tokens += sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "reasoning_output_tokens"))
            elif t in ("turn.failed", "error"):
                errors.append(json.dumps(ev.get("error") or ev.get("message") or ev)[:500])
            elif t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                last_msg = ev["item"].get("text", "")
        if p.returncode != 0 or (errors and not (final or last_msg)):
            raise classify(" | ".join(errors) or p.stderr or f"exit {p.returncode}")
        return EngineResult(text=final or last_msg, tokens=tokens, model=self.model or "codex-default")


# ---------------------------------------------------------------------------  HTTP providers
Transport = Callable[[str, str, dict, bytes | None, int], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: int) -> tuple[int, bytes]:
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


class _HTTPBase:
    name = "http"
    agentic = False
    model = ""
    key_env = ""
    local = False

    def __init__(self, transport: Transport | None = None):
        self.transport = transport or _urllib_transport

    def _call(self, method: str, url: str, headers: dict, payload: dict | None, timeout: int) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ai-game-studio/1.3", **headers}
        try:
            status, raw = self.transport(method, url, h, body, timeout)
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            raise EngineUnavailable(f"{self.name}: cannot reach {url.split('?')[0]}: {e}") from e
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            data = {"_raw": text[:1000]}
        if status == 429:
            raise RateLimited(f"{self.name} 429: {text[:500]}")
        if status in (401, 403):
            raise EngineUnavailable(f"{self.name} {status}: key missing, wrong or without access. {text[:300]}")
        if status == 404 and self.local:
            raise EngineUnavailable(f"{self.name} 404 at {url}: is the server running and the model pulled/loaded? {text[:300]}")
        if status >= 500 and status != 529:
            raise EngineError(f"{self.name} server error {status}: {text[:500]}")
        if status == 529:
            raise RateLimited(f"{self.name} overloaded (529): {text[:300]}")
        if status >= 400:
            raise classify(f"{self.name} {status}: {text[:800]}")
        return data

    def _need_key(self, key: str | None) -> str:
        if not key:
            raise EngineUnavailable(f"{self.key_env} is not set. Add it in the setup wizard (saved to Keychain/.env).")
        return key

    def test(self, deep: bool = False) -> dict:
        t0 = time.time()
        try:
            detail = self.ping()
            if deep:
                r = self.run(EngineRequest(prompt="Reply with the single word OK.", cwd=Path(tempfile.gettempdir()),
                                           role="setup", task="setup.test", timeout=60))
                detail += f"; replied '{r.text.strip()[:40]}' ({r.tokens} tokens)"
        except EngineError as e:
            return _fail(f"{type(e).__name__}: {e}", self.fix_hint())
        return _ok(detail, latency_ms=int((time.time() - t0) * 1000))

    def fix_hint(self) -> str:
        return f"Check {self.key_env} in the wizard's Keys step." if self.key_env else ""

    def ping(self) -> str:
        raise NotImplementedError


def _messages(req: EngineRequest) -> list[dict]:
    return [{"role": "user", "content": req.prompt}]


class OpenAICompatEngine(_HTTPBase):
    """Any OpenAI-compatible Chat Completions endpoint: OpenRouter (https://openrouter.ai/api/v1) and LM Studio
    (http://127.0.0.1:1234/v1, `lms server start`). POST {base}/chat/completions; GET {base}/models."""
    agentic = False

    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None, key_env: str = "",
                 extra_headers: dict | None = None, local: bool = False, max_tokens: int = 0, transport: Transport | None = None):
        super().__init__(transport)
        self.name, self.base, self.model, self.api_key, self.key_env = name, base_url.rstrip("/"), model, api_key, key_env
        self.extra_headers, self.local, self.max_tokens = extra_headers or {}, local, max_tokens

    def _headers(self) -> dict:
        h = dict(self.extra_headers)
        if self.key_env:
            h["Authorization"] = "Bearer " + self._need_key(self.api_key)
        elif self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def _model(self) -> str:
        if self.model:
            return self.model
        if self.local:    # LM Studio: use whatever model is loaded
            ids = self.list_models()
            if ids:
                return ids[0]
        raise EngineUnavailable(f"{self.name}: no model set (Settings > model defaults)")

    def list_models(self) -> list[str]:
        data = self._call("GET", self.base + "/models", self._headers(), None, 20)
        return [m.get("id", "") for m in (data.get("data") or []) if isinstance(m, dict)]

    def ping(self) -> str:
        ids = self.list_models()
        has = (not self.model) or self.model in ids or not ids
        return f"{len(ids)} models visible" + ("" if has else f"; WARNING: '{self.model}' not in the list")

    def run(self, req: EngineRequest) -> EngineResult:
        payload = {"model": self._model(), "messages": _messages(req)}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        data = self._call("POST", self.base + "/chat/completions", self._headers(), payload, req.timeout)
        if data.get("error"):
            raise classify(json.dumps(data["error"])[:800])
        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise EngineError(f"{self.name}: unexpected reply {str(data)[:300]}") from e
        u = data.get("usage") or {}
        tokens = int(u.get("total_tokens") or (int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0)))
        return EngineResult(text=text, tokens=tokens, model=data.get("model") or payload["model"])


class OpenAIEngine(_HTTPBase):
    """OpenAI API, Responses endpoint (POST https://api.openai.com/v1/responses, `input` -> `output_text`).
    Key: OPENAI_API_KEY. Models per https://developers.openai.com/api/docs/models (checked 2026-10-28)."""
    name = "openai"
    agentic = False
    key_env = "OPENAI_API_KEY"

    def __init__(self, model: str = "gpt-6.1-sol", api_key: str | None = None, base_url: str = "https://api.openai.com/v1",
                 effort: str = "", transport: Transport | None = None):
        super().__init__(transport)
        self.model, self.api_key, self.base, self.effort = model or "gpt-6.1-sol", api_key, base_url.rstrip("/"), effort

    def _h(self) -> dict:
        return {"Authorization": "Bearer " + self._need_key(self.api_key)}

    def ping(self) -> str:
        data = self._call("GET", self.base + "/models", self._h(), None, 20)
        ids = [m.get("id") for m in data.get("data") or []]
        return f"{len(ids)} models visible" + ("" if self.model in ids or not ids else f"; WARNING: '{self.model}' not listed")

    def run(self, req: EngineRequest) -> EngineResult:
        payload: dict = {"model": self.model, "input": req.prompt}
        if self.effort:
            payload["reasoning"] = {"effort": self.effort}
        data = self._call("POST", self.base + "/responses", self._h(), payload, req.timeout)
        if data.get("error"):
            raise classify(json.dumps(data["error"])[:800])
        text = data.get("output_text") or ""
        if not text:
            for item in data.get("output") or []:
                if item.get("type") == "message":
                    for c in item.get("content") or []:
                        if c.get("type") in ("output_text", "text"):
                            text += c.get("text", "")
        u = data.get("usage") or {}
        tokens = int(u.get("total_tokens") or (int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)))
        return EngineResult(text=text, tokens=tokens, model=data.get("model") or self.model)


class AnthropicEngine(_HTTPBase):
    """Anthropic Messages API (POST https://api.anthropic.com/v1/messages, headers x-api-key + anthropic-version).
    Key: ANTHROPIC_API_KEY. Models per https://platform.claude.com/docs/en/about-claude/models/overview (2026-10-28)."""
    name = "anthropic"
    agentic = False
    key_env = "ANTHROPIC_API_KEY"
    VERSION = "2023-06-01"

    def __init__(self, model: str = "claude-sonnet-5-5", api_key: str | None = None, base_url: str = "https://api.anthropic.com",
                 max_tokens: int = 16000, transport: Transport | None = None):
        super().__init__(transport)
        self.model, self.api_key, self.base, self.max_tokens = model or "claude-sonnet-5-5", api_key, base_url.rstrip("/"), max_tokens

    def _h(self) -> dict:
        return {"x-api-key": self._need_key(self.api_key), "anthropic-version": self.VERSION}

    def ping(self) -> str:
        data = self._call("GET", self.base + "/v1/models", self._h(), None, 20)
        ids = [m.get("id") for m in data.get("data") or []]
        return f"{len(ids)} models visible" + ("" if self.model in ids or not ids else f"; WARNING: '{self.model}' not listed")

    def run(self, req: EngineRequest) -> EngineResult:
        payload = {"model": self.model, "max_tokens": self.max_tokens, "messages": _messages(req)}
        data = self._call("POST", self.base + "/v1/messages", self._h(), payload, req.timeout)
        if data.get("type") == "error":
            raise classify(json.dumps(data.get("error"))[:800])
        text = "".join(c.get("text", "") for c in data.get("content") or [] if c.get("type") == "text")
        u = data.get("usage") or {}
        tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))
        return EngineResult(text=text, tokens=tokens, model=data.get("model") or self.model)


class GeminiAPIEngine(_HTTPBase):
    """Gemini Developer API over REST (POST {base}/models/{model}:generateContent, header x-goog-api-key).
    Key: GEMINI_API_KEY from https://aistudio.google.com/apikey. Separate from the Google AI Pro subscription."""
    name = "genai"
    agentic = False
    key_env = "GEMINI_API_KEY"

    def __init__(self, model: str = "gemini-3.8-flash", api_key: str | None = None,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta", transport: Transport | None = None):
        super().__init__(transport)
        self.model, self.api_key, self.base = model or "gemini-3.8-flash", api_key, base_url.rstrip("/")

    def _h(self) -> dict:
        return {"x-goog-api-key": self._need_key(self.api_key)}

    def ping(self) -> str:
        data = self._call("GET", self.base + "/models?pageSize=200", self._h(), None, 20)
        ids = [str(m.get("name", "")).removeprefix("models/") for m in data.get("models") or []]
        return f"{len(ids)} models visible" + ("" if self.model in ids or not ids else f"; WARNING: '{self.model}' not listed")

    def run(self, req: EngineRequest) -> EngineResult:
        payload = {"contents": [{"role": "user", "parts": [{"text": req.prompt}]}]}
        data = self._call("POST", f"{self.base}/models/{self.model}:generateContent", self._h(), payload, req.timeout)
        if data.get("error"):
            raise classify(json.dumps(data["error"])[:800])
        parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        um = data.get("usageMetadata") or {}
        return EngineResult(text=text, tokens=int(um.get("totalTokenCount") or 0), model=self.model)


# backward-compatible name used by older tests/imports
GenAIEngine = GeminiAPIEngine


class OllamaEngine(_HTTPBase):
    """Local Ollama (https://docs.ollama.com). Native POST /api/chat so the context size can be raised
    (Ollama's default context is 4096 tokens, too small for studio prompts). Not agentic."""
    name = "ollama"
    agentic = False
    local = True

    def __init__(self, host: str = "http://127.0.0.1:11434", model: str = "qwen2.5-coder:7b", num_ctx: int = 16384,
                 transport: Transport | None = None):
        super().__init__(transport)
        self.host, self.model, self.num_ctx = host.rstrip("/"), model or "qwen2.5-coder:7b", num_ctx

    def fix_hint(self) -> str:
        return f"Start Ollama (the app, or `ollama serve`) and run `ollama pull {self.model}`."

    def ping(self) -> str:
        data = self._call("GET", self.host + "/api/tags", {}, None, 10)
        names = [m.get("name", "") for m in data.get("models") or []]
        if self.model not in names and f"{self.model}:latest" not in names:
            raise EngineUnavailable(f"Ollama is running but '{self.model}' is not pulled (have: {', '.join(names[:8]) or 'none'})")
        return f"Ollama up, {len(names)} local models, '{self.model}' ready"

    def run(self, req: EngineRequest) -> EngineResult:
        payload = {"model": self.model, "messages": _messages(req), "stream": False, "options": {"num_ctx": self.num_ctx}}
        data = self._call("POST", self.host + "/api/chat", {}, payload, req.timeout)
        if data.get("error"):
            raise EngineError(f"ollama: {data['error']}")
        return EngineResult(text=(data.get("message") or {}).get("content", ""), model=self.model,
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

    model = "fake"

    def script(self, task: str, item) -> None:
        self._scripts.setdefault(task, []).append(item)

    def test(self, deep: bool = False) -> dict:
        return _ok("mock provider ready (offline, deterministic)")

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
        elif t == "qa.launch_audit":
            out = {"summary": "No blockers found by the QA/Compliance review.",
                   "items": [{"area": "performance", "check": "Startup under 5 s on a mid-range phone", "verdict": "TODO",
                              "blocker": False, "fix": "Measure on Murali's device before production"},
                             {"area": "policy", "check": "Data safety form matches SDKs (AdMob, Billing)", "verdict": "PASS",
                              "blocker": False, "fix": ""}]}
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




# ---------------------------------------------------------------------------  registry
CHECKED = "2026-10-28"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str                      # cli | api | local | test
    agentic: bool
    model_setting: str = ""        # settings key holding this provider's default model
    default_model: str = ""
    models: tuple = ()             # suggestions shown in the wizard (verify against the provider's docs)
    key_env: str = ""              # env var / Keychain account for the API key ('' = none)
    bin_setting: str = ""
    url_setting: str = ""
    cost_note: str = ""
    docs: str = ""
    install: str = ""


PROVIDERS: dict[str, ProviderSpec] = {p.id: p for p in [
    ProviderSpec("agy", "Antigravity CLI (Google AI Pro)", "cli", True, "agy_model", "",
                 (), "", "agy_bin", "",
                 f"Included in your Google AI Pro subscription; usage counts against the plan's Antigravity quota "
                 f"(see /usage inside agy). No per-token bill. Checked {CHECKED}.",
                 "https://antigravity.google/docs/cli/headless", "Google's installer; then run `agy` once and sign in."),
    ProviderSpec("claude_code", "Claude Code CLI", "cli", True, "claude_model", "",
                 ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"), "", "claude_bin", "",
                 f"With a Claude Pro/Max login: covered by the subscription's usage limits. With ANTHROPIC_API_KEY "
                 f"(claude_use_api_key=1): billed per token at API prices; the JSON reply includes an estimated "
                 f"total_cost_usd. Checked {CHECKED}.",
                 "https://code.claude.com/docs/en/headless", "curl -fsSL https://claude.ai/install.sh | bash"),
    ProviderSpec("codex", "OpenAI Codex CLI", "cli", True, "codex_model", "",
                 ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-5.3-codex"), "", "codex_bin", "",
                 f"Signed in with ChatGPT: counts against your ChatGPT plan's Codex limits. With an API key: billed "
                 f"per token at OpenAI API prices. Checked {CHECKED}.",
                 "https://developers.openai.com/codex/noninteractive", "brew install --cask codex"),
    ProviderSpec("gemini_cli", "Gemini CLI (legacy)", "cli", True, "gemini_model", "",
                 ("gemini-3.8-flash",), "", "gemini_bin", "",
                 f"Personal Google AI Pro login stopped working on 2026-06-18; use only with GEMINI_API_KEY "
                 f"(pay-as-you-go, same prices as the Gemini API). Checked {CHECKED}.",
                 "https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli",
                 "npm install -g @google/gemini-cli"),
    ProviderSpec("genai", "Gemini API (API key)", "api", False, "genai_model", "gemini-3.8-flash",
                 ("gemini-3.8-flash", "gemini-4-argon", "gemini-3.5-flash-lite"), "GEMINI_API_KEY", "", "gemini_api_base",
                 f"Free tier for gemini-3.8-flash / 3.5-flash-lite (prompts may be used to improve Google products). "
                 f"Paid: gemini-3.8-flash $0.75 in / $3.75 out per 1M tokens until 2026-12-31, then $1.50 / $7.50; "
                 f"gemini-4-argon $2 / $10 until 2026-11-30, then $4 / $20 (no free tier). Checked {CHECKED}.",
                 "https://ai.google.dev/gemini-api/docs/pricing", "Key from https://aistudio.google.com/apikey"),
    ProviderSpec("anthropic", "Anthropic Claude API", "api", False, "anthropic_model", "claude-sonnet-5-5",
                 ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"), "ANTHROPIC_API_KEY", "",
                 "anthropic_base",
                 f"Per 1M tokens: Sonnet 5.5 $2 in / $10 out, Opus 5.5 $4 / $20, Haiku 5.5 from $0.10 / $0.50, "
                 f"Fable 5.1 $10 / $50. Prepaid credits; no free tier. Checked {CHECKED}.",
                 "https://platform.claude.com/docs/en/about-claude/models/overview", "Key from https://platform.claude.com"),
    ProviderSpec("openai", "OpenAI API", "api", False, "openai_model", "gpt-6.1-sol",
                 ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna", "gpt-6-astra"), "OPENAI_API_KEY", "", "openai_base",
                 f"Per 1M tokens: gpt-6.1-sol $2 in / $10 out, gpt-6.1-terra $1 / $5, gpt-6-luna $0.10 / $0.50, "
                 f"gpt-6-astra $10 / $50. Billed separately from ChatGPT plans. Checked {CHECKED}.",
                 "https://developers.openai.com/api/docs/pricing", "Key from https://platform.openai.com/api-keys"),
    ProviderSpec("openrouter", "OpenRouter", "api", False, "openrouter_model", "anthropic/claude-sonnet-5.5",
                 ("anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash", "openai/gpt-6.1-sol", "openrouter/free"),
                 "OPENROUTER_API_KEY", "", "openrouter_base",
                 f"Passes through each provider's token price (no inference markup); a fee is charged when you buy "
                 f"credits. Free models: 50 requests/day (1000/day after buying 10 credits). Checked {CHECKED}.",
                 "https://openrouter.ai/docs/faq", "Key from https://openrouter.ai/keys"),
    ProviderSpec("ollama", "Ollama (local)", "local", False, "ollama_model", "qwen2.5-coder:7b",
                 ("qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen2.5-coder:3b"), "", "", "ollama_host",
                 "Free, runs on your Mac. 16 GB RAM: 7B (4.7 GB download) is comfortable, 14B (9.0 GB) works if "
                 f"little else is open; 32B (20 GB) does not fit. Checked {CHECKED}.",
                 "https://docs.ollama.com", "Download the app from https://ollama.com/download"),
    ProviderSpec("lmstudio", "LM Studio (local)", "local", False, "lmstudio_model", "",
                 ("qwen2.5-coder-7b-instruct", "qwen2.5-coder-14b-instruct"), "", "", "lmstudio_base",
                 f"Free, runs on your Mac (MLX models on Apple Silicon). Same RAM limits as Ollama. Checked {CHECKED}.",
                 "https://lmstudio.ai/docs/developer/openai-compat", "Download from https://lmstudio.ai, then `lms server start`"),
    ProviderSpec("fake", "Mock provider (tests/demo)", "test", True, "", "", (), "", "", "",
                 "Free, offline, deterministic. Used by pytest and `./run.sh demo`.", "", ""),
]}

ENGINE_IDS = list(PROVIDERS)
SecretGetter = Callable[[str], "str | None"]


def _env_get(name: str) -> str | None:
    return os.environ.get(name) or None


def build_engine(name: str, s: dict[str, str], fake: FakeEngine | None = None, secret: SecretGetter | None = None,
                 transport: Transport | None = None) -> Engine:
    """Create the provider `name` from the settings dict `s`. `secret(name)` resolves API keys (env > Keychain > .env)."""
    name = (name or "agy").strip()
    if name == "mock":
        name = "fake"
    get = secret or _env_get
    num = lambda k, d: int(float(s.get(k) or d))  # noqa: E731
    if name == "agy":
        return AntigravityCLIEngine(s.get("agy_bin", "agy"), s.get("agy_model", ""), s.get("agy_effort", ""),
                                    s.get("agy_skip_permissions") == "1")
    if name == "gemini_cli":
        return GeminiCLIEngine(s.get("gemini_bin", "gemini"), s.get("gemini_model", ""))
    if name == "claude_code":
        return ClaudeCodeCLIEngine(s.get("claude_bin", "claude"), s.get("claude_model", ""),
                                   s.get("claude_permission_mode", "acceptEdits"), get("ANTHROPIC_API_KEY"),
                                   s.get("claude_use_api_key") == "1")
    if name == "codex":
        return CodexCLIEngine(s.get("codex_bin", "codex"), s.get("codex_model", ""),
                              get("CODEX_API_KEY") if s.get("codex_use_api_key") == "1" else None)
    if name == "genai":
        return GeminiAPIEngine(s.get("genai_model") or "gemini-3.8-flash", get("GEMINI_API_KEY") or get("GOOGLE_API_KEY"),
                               s.get("gemini_api_base") or "https://generativelanguage.googleapis.com/v1beta", transport)
    if name == "anthropic":
        return AnthropicEngine(s.get("anthropic_model") or "claude-sonnet-5-5", get("ANTHROPIC_API_KEY"),
                               s.get("anthropic_base") or "https://api.anthropic.com", num("anthropic_max_tokens", 16000), transport)
    if name == "openai":
        return OpenAIEngine(s.get("openai_model") or "gpt-6.1-sol", get("OPENAI_API_KEY"),
                            s.get("openai_base") or "https://api.openai.com/v1", s.get("openai_effort", ""), transport)
    if name == "openrouter":
        return OpenAICompatEngine("openrouter", s.get("openrouter_base") or "https://openrouter.ai/api/v1",
                                  s.get("openrouter_model") or "anthropic/claude-sonnet-5.5", get("OPENROUTER_API_KEY"),
                                  "OPENROUTER_API_KEY", {"X-Title": "AI Game Studio (local)"}, transport=transport)
    if name == "ollama":
        return OllamaEngine(s.get("ollama_host") or "http://127.0.0.1:11434", s.get("ollama_model") or "qwen2.5-coder:7b",
                            num("ollama_num_ctx", 16384), transport)
    if name == "lmstudio":
        return OpenAICompatEngine("lmstudio", s.get("lmstudio_base") or "http://127.0.0.1:1234/v1", s.get("lmstudio_model", ""),
                                  None, "", local=True, transport=transport)
    if name == "fake":
        return fake or FakeEngine()
    raise EngineUnavailable(f"unknown engine '{name}' (known: {', '.join(ENGINE_IDS)})")


def check_provider(name: str, s: dict[str, str], deep: bool = False, secret: SecretGetter | None = None,
                  fake: FakeEngine | None = None, transport: Transport | None = None) -> dict:
    """'Test connection' for one provider. Never raises; never returns a key."""
    spec = PROVIDERS.get("fake" if name == "mock" else name)
    if not spec:
        return _fail(f"unknown provider '{name}'")
    try:
        eng = build_engine(spec.id, s, fake, secret, transport)
    except EngineError as e:
        return _fail(str(e))
    tester = getattr(eng, "test", None)
    res = tester(deep) if tester else _ok("no test available")
    return {"provider": spec.id, "label": spec.label, **res}
