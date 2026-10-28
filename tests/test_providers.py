"""Provider layer: every API/local provider against a fake HTTP transport, the new CLI agents against stub
binaries, error classification, the registry, per-role provider + model selection, and the key store."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from studio.engines import (PROVIDERS, AnthropicEngine, ClaudeCodeCLIEngine, CodexCLIEngine, EngineRequest,
                            EngineUnavailable, FakeEngine, GeminiAPIEngine, OllamaEngine, OpenAICompatEngine,
                            OpenAIEngine, RateLimited, build_engine, check_provider)
from studio.keystore import Keychain, SecretStore, mask
from studio.prompts import extract_json
from studio.worker import run_until_idle
from conftest import pending

REPLY = '```json\n{"summary": "ok"}\n```'


class FakeHTTP:
    """Records requests; answers by the first route whose key is a substring of the URL."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": json.loads(body) if body else None})
        for k, v in self.routes.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                status, payload = v
                return status, json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        return 404, b'{"error":"no route"}'


def req(tmp_path, edit=False, task="ticket.work"):
    return EngineRequest(prompt="hello", cwd=tmp_path, role="engineer", task=task, edit=edit, timeout=30)


# ------------------------------------------------------------------ HTTP providers
def test_openai_responses_api(tmp_path):
    t = FakeHTTP({"/responses": (200, {"model": "gpt-6.1-sol", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": REPLY}]}], "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}})})
    r = OpenAIEngine("gpt-6.1-sol", "sk-test", transport=t, effort="low").run(req(tmp_path))
    assert extract_json(r.text) == {"summary": "ok"} and r.tokens == 15
    c = t.calls[0]
    assert c["url"] == "https://api.openai.com/v1/responses" and c["headers"]["Authorization"] == "Bearer sk-test"
    assert c["body"] == {"model": "gpt-6.1-sol", "input": "hello", "reasoning": {"effort": "low"}}


def test_anthropic_messages_api(tmp_path):
    t = FakeHTTP({"/v1/messages": (200, {"type": "message", "model": "claude-sonnet-5-5",
                                         "content": [{"type": "text", "text": REPLY}],
                                         "usage": {"input_tokens": 7, "output_tokens": 3}})})
    r = AnthropicEngine("claude-sonnet-5-5", "ak", transport=t, max_tokens=1234).run(req(tmp_path))
    assert extract_json(r.text)["summary"] == "ok" and r.tokens == 10
    h, b = t.calls[0]["headers"], t.calls[0]["body"]
    assert h["x-api-key"] == "ak" and h["anthropic-version"] == "2023-06-01"
    assert b["model"] == "claude-sonnet-5-5" and b["max_tokens"] == 1234 and b["messages"][0]["content"] == "hello"


def test_gemini_api_generate_content(tmp_path):
    t = FakeHTTP({":generateContent": (200, {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True},
                                                                                   {"text": REPLY}]}}],
                                            "usageMetadata": {"totalTokenCount": 42}})})
    r = GeminiAPIEngine("gemini-3.8-flash", "gk", transport=t).run(req(tmp_path))
    assert r.text == REPLY and r.tokens == 42
    assert t.calls[0]["url"].endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    assert t.calls[0]["headers"]["x-goog-api-key"] == "gk"


def test_openrouter_and_lmstudio_chat_completions(tmp_path):
    t = FakeHTTP({"/chat/completions": (200, {"model": "x", "choices": [{"message": {"content": REPLY}}],
                                              "usage": {"prompt_tokens": 4, "completion_tokens": 2}}),
                  "/models": (200, {"data": [{"id": "qwen2.5-coder-7b-instruct"}]})})
    s = {"openrouter_model": "anthropic/claude-sonnet-5.5"}
    eng = build_engine("openrouter", s, secret=lambda k: "or-key" if k == "OPENROUTER_API_KEY" else None, transport=t)
    r = eng.run(req(tmp_path))
    assert r.tokens == 6 and t.calls[-1]["headers"]["Authorization"] == "Bearer or-key"
    assert t.calls[-1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert t.calls[-1]["body"]["model"] == "anthropic/claude-sonnet-5.5"
    # LM Studio without a model setting uses the loaded model and sends no key
    lm = build_engine("lmstudio", {}, transport=t)
    lm.run(req(tmp_path))
    assert t.calls[-1]["body"]["model"] == "qwen2.5-coder-7b-instruct" and "Authorization" not in t.calls[-1]["headers"]
    assert t.calls[-1]["url"].startswith("http://127.0.0.1:1234/v1/")


def test_ollama_native_chat_with_context(tmp_path):
    t = FakeHTTP({"/api/chat": (200, {"message": {"content": REPLY}, "prompt_eval_count": 9, "eval_count": 1}),
                  "/api/tags": (200, {"models": [{"name": "qwen2.5-coder:7b"}]})})
    e = OllamaEngine("http://127.0.0.1:11434", "qwen2.5-coder:7b", 16384, transport=t)
    r = e.run(req(tmp_path))
    assert r.tokens == 10 and t.calls[0]["body"]["options"]["num_ctx"] == 16384 and t.calls[0]["body"]["stream"] is False
    assert e.test()["ok"]
    assert not OllamaEngine(model="qwen2.5-coder:14b", transport=t).test()["ok"]   # not pulled -> clear failure


def test_http_errors_are_classified(tmp_path):
    with pytest.raises(RateLimited):
        AnthropicEngine(api_key="k", transport=FakeHTTP({"/v1/messages": (429, {"error": "rate"})})).run(req(tmp_path))
    with pytest.raises(RateLimited):
        AnthropicEngine(api_key="k", transport=FakeHTTP({"/v1/messages": (529, {"error": "overloaded"})})).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):
        OpenAIEngine(api_key="bad", transport=FakeHTTP({"/responses": (401, {"error": "invalid key"})})).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):          # no key at all: pause the queue, don't burn attempts
        GeminiAPIEngine(api_key=None, transport=FakeHTTP({})).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):          # local server down
        OllamaEngine(transport=FakeHTTP({"/api/chat": ConnectionRefusedError("refused")})).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):          # real socket, nothing listening
        OpenAICompatEngine("lmstudio", "http://127.0.0.1:9/v1", "m", local=True).run(req(tmp_path))


# ------------------------------------------------------------------ CLI agents (stub binaries)
def stub(tmp_path: Path, name: str, stdout: str, code: int = 0, write_last: str | None = None) -> str:
    p = tmp_path / name
    extra = ""
    if write_last is not None:   # emulate `codex exec -o <file>`
        extra = f'while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then shift; printf %s \'{write_last}\' > "$1"; fi; shift; done\n'
    p.write_text(f"#!/bin/sh\necho \"$@\" > '{tmp_path}/{name}.args'\nenv > '{tmp_path}/{name}.env'\n"
                 f"cat <<'EOF'\n{stdout}\nEOF\n{extra}exit {code}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_claude_code_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")   # secretscan: allow
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": REPLY, "session_id": "s1",
                      "total_cost_usd": 0.0123, "usage": {"input_tokens": 100, "output_tokens": 20}})
    e = ClaudeCodeCLIEngine(stub(tmp_path, "claude", out), model="claude-sonnet-5-5")
    r = e.run(req(tmp_path, edit=True))
    assert r.tokens == 120 and r.cost_usd == 0.0123 and extract_json(r.text) == {"summary": "ok"}
    args = (tmp_path / "claude.args").read_text()
    assert "-p hello" in args and "--output-format json" in args and "--model claude-sonnet-5-5" in args
    assert "--permission-mode acceptEdits" in args
    # subscription login by default: the API key is NOT handed to Claude Code (it would bill the API instead)
    assert "ANTHROPIC_API_KEY" not in (tmp_path / "claude.env").read_text()
    e.run(req(tmp_path, edit=False))
    assert "--allowedTools Read" in (tmp_path / "claude.args").read_text()
    err = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key - please run /login"})
    with pytest.raises(EngineUnavailable):
        ClaudeCodeCLIEngine(stub(tmp_path, "claude2", err, 1)).run(req(tmp_path))


def test_codex_cli(tmp_path):
    events = "\n".join(json.dumps(e) for e in [
        {"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "draft"}},
        {"type": "turn.completed", "usage": {"input_tokens": 50, "cached_input_tokens": 40, "output_tokens": 7}}])
    e = CodexCLIEngine(stub(tmp_path, "codex", events, write_last=REPLY.replace("\n", " ")), model="gpt-6.1-sol")
    r = e.run(req(tmp_path, edit=True))
    assert r.tokens == 57 and extract_json(r.text) == {"summary": "ok"}
    args = (tmp_path / "codex.args").read_text()
    for f in ("exec", "--json", "--sandbox workspace-write", "-m gpt-6.1-sol", "--skip-git-repo-check"):
        assert f in args
    e.run(req(tmp_path, edit=False))
    assert "--sandbox read-only" in (tmp_path / "codex.args").read_text()
    with pytest.raises(RateLimited):
        CodexCLIEngine(stub(tmp_path, "codex2", json.dumps({"type": "turn.failed", "error": {"message": "429 Too Many Requests"}}), 1)).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):
        CodexCLIEngine(str(tmp_path / "missing-codex")).run(req(tmp_path))


def test_cli_connection_test_uses_version(tmp_path):
    p = tmp_path / "agy"
    p.write_text("#!/bin/sh\necho 'agy 1.4.2'\n")
    p.chmod(0o755)
    res = check_provider("agy", {"agy_bin": str(p)})
    assert res["ok"] and "agy 1.4.2" in res["detail"]
    res = check_provider("claude_code", {"claude_bin": str(tmp_path / "nope")})
    assert not res["ok"] and "install" in res["fix"].lower()


# ------------------------------------------------------------------ registry
def test_registry_builds_every_provider_and_tests_never_leak_keys():
    t = FakeHTTP({"/models": (200, {"data": [{"id": "gpt-6.1-sol"}], "models": [{"name": "models/gemini-3.8-flash"}]}),
                  "/v1/models": (200, {"data": [{"id": "claude-sonnet-5-5"}]}),
                  "/api/tags": (200, {"models": [{"name": "qwen2.5-coder:7b"}]})})
    secret = lambda k: f"secret-value-for-{k}"  # noqa: E731
    for pid, spec in PROVIDERS.items():
        eng = build_engine(pid, {}, FakeEngine(), secret, t)
        assert eng.name == pid and eng.agentic == spec.agentic
        assert spec.cost_note and ("2026-10-28" in spec.cost_note or spec.kind in ("test",))
        res = check_provider(pid, {}, False, secret, FakeEngine(), t)
        assert "secret-value" not in json.dumps(res)
        if spec.kind in ("api", "local", "test"):
            assert res["ok"], (pid, res)
    assert build_engine("mock", {}, FakeEngine()).name == "fake"
    with pytest.raises(EngineUnavailable):
        build_engine("nope", {})


# ------------------------------------------------------------------ per-role provider + model
def test_each_role_uses_its_own_provider_and_model(studio, fake):
    st = studio
    t = FakeHTTP({"/v1/messages": (200, {"content": [{"type": "text", "text": '```json\n{"title":"Orbit","logline":"x","pitch_markdown":"# Orbit"}\n```'}],
                                         "usage": {"input_tokens": 1, "output_tokens": 1}}),
                  "/responses": (200, {"output_text": '```json\n{"standup_markdown":"## ok"}\n```', "usage": {"total_tokens": 3}})})
    st.http_transport = t
    st.secrets.set("ANTHROPIC_API_KEY", "ak-1", "env")
    st.secrets.set("OPENAI_API_KEY", "ok-1", "env")
    st.apply_roles({"designer": {"engine": "anthropic", "model": "claude-opus-5-5"},
                    "producer": {"engine": "openai", "model": "gpt-6.1-terra"}})
    assert st.engine_for("designer", "designer.pitch").model == "claude-opus-5-5"
    assert st.engine_for("producer", "producer.standup").model == "gpt-6.1-terra"
    assert st.engine_for("engineer", "ticket.work").name == "fake"     # untouched roles keep the default
    gid = st.new_game("space hopper")
    run_until_idle(st)
    assert pending(st, 1) and t.calls[0]["body"]["model"] == "claude-opus-5-5"
    assert t.calls[0]["headers"]["x-api-key"] == "ak-1"
    st.request_standup(gid)
    run_until_idle(st)
    assert t.calls[-1]["body"]["model"] == "gpt-6.1-terra"
    runs = st.db.all("SELECT agent, engine, model FROM runs ORDER BY id")
    assert ("designer", "anthropic") in {(r["agent"], r["engine"]) for r in runs}
    assert ("producer", "openai") in {(r["agent"], r["engine"]) for r in runs}
    # the key is never in the database
    dump = json.dumps(st.db.all("SELECT * FROM settings")) + json.dumps(st.db.all("SELECT * FROM events"))
    assert "ak-1" not in dump and "ok-1" not in dump


# ------------------------------------------------------------------ key store
def test_keystore_env_file_and_masking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = SecretStore(tmp_path / ".env", Keychain(force=False))
    assert s.available_backends() == ["env"]
    with pytest.raises(ValueError):
        s.set("OPENAI_API_KEY", "x", "keychain")
    res = s.set("OPENAI_API_KEY", "sk-1234567890abcdef", "env")
    assert res == {"name": "OPENAI_API_KEY", "set": True, "masked": "sk-1...cdef", "source": ".env"}
    assert oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o600"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert s.get("OPENAI_API_KEY") == "sk-1234567890abcdef" and s.source("OPENAI_API_KEY") == ".env"
    s.set("OPENAI_API_KEY", "sk-new-value-0000", "env")          # replaced, not duplicated
    assert (tmp_path / ".env").read_text().count("OPENAI_API_KEY=") == 1
    with pytest.raises(ValueError):
        s.set("bad name", "v", "env")
    assert mask("abc") == "***" and mask("") == ""


def test_keychain_backend_uses_security_tool(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls, store = [], {}

    def runner(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "add-generic-password":
            store[cmd[cmd.index("-a") + 1]] = cmd[cmd.index("-w") + 1]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1] == "find-generic-password":
            v = store.get(cmd[cmd.index("-a") + 1])
            return subprocess.CompletedProcess(cmd, 0 if v else 44, (v or "") + "\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    s = SecretStore(tmp_path / ".env", Keychain(runner=runner, force=True))
    assert s.set("ANTHROPIC_API_KEY", "sk-ant-xyz-123456", "keychain")["source"] == "keychain"   # secretscan: allow
    assert calls[0][:2] == ["security", "add-generic-password"] and "-U" in calls[0] and "ai-game-studio" in calls[0]
    assert not (tmp_path / ".env").exists()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert s.get("ANTHROPIC_API_KEY") == "sk-ant-xyz-123456" and s.source("ANTHROPIC_API_KEY") == "keychain"
