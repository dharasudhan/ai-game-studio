"""CLI adapters exercised end-to-end against stub binaries that mimic agy / gemini JSON output."""
import json
import os
import stat
from pathlib import Path

import pytest

from studio.engines import (AntigravityCLIEngine, EngineError, EngineRequest, EngineUnavailable, GeminiCLIEngine,
                            OllamaEngine, RateLimited)
from studio.prompts import extract_json


def stub(tmp_path: Path, name: str, stdout: str, code: int = 0) -> str:
    p = tmp_path / name
    p.write_text(f"#!/bin/sh\necho \"$@\" > '{tmp_path}/{name}.args'\ncat <<'EOF'\n{stdout}\nEOF\nexit {code}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def req(tmp_path, edit=False):
    return EngineRequest(prompt="hello", cwd=tmp_path, role="engineer", task="ticket.work", edit=edit, timeout=30)


def test_agy_success_and_flags(tmp_path):
    out = json.dumps({"conversation_id": "c1", "status": "SUCCESS", "response": "```json\n{\"summary\":\"ok\"}\n```",
                      "usage": {"total_tokens": 123}})
    e = AntigravityCLIEngine(stub(tmp_path, "agy", out), model="gemini-3.8-flash-medium", effort="low", skip_permissions=True)
    r = e.run(req(tmp_path, edit=True))
    assert r.tokens == 123 and extract_json(r.text) == {"summary": "ok"}
    args = (tmp_path / "agy.args").read_text()
    for f in ("-p hello", "--output-format json", "--model gemini-3.8-flash-medium", "--effort low", "--dangerously-skip-permissions", "--print-timeout"):
        assert f in args
    e.run(req(tmp_path, edit=False))
    assert "--dangerously-skip-permissions" not in (tmp_path / "agy.args").read_text()


def test_agy_error_classification(tmp_path):
    rl = json.dumps({"status": "ERROR", "error": "RESOURCE_EXHAUSTED: quota exceeded", "response": ""})
    with pytest.raises(RateLimited):
        AntigravityCLIEngine(stub(tmp_path, "agy", rl, 1)).run(req(tmp_path))
    auth = json.dumps({"status": "ERROR", "error": "authentication required", "response": ""})
    with pytest.raises(EngineUnavailable):
        AntigravityCLIEngine(stub(tmp_path, "agy2", auth, 1)).run(req(tmp_path))
    with pytest.raises(EngineError):
        AntigravityCLIEngine(stub(tmp_path, "agy3", "", 1)).run(req(tmp_path))
    with pytest.raises(EngineUnavailable):
        AntigravityCLIEngine(str(tmp_path / "missing-agy")).run(req(tmp_path))


def test_gemini_cli(tmp_path):
    out = json.dumps({"response": "{\"summary\": \"hi\"}", "stats": {"models": {"m": {"tokens": {"total": 7}}}}})
    e = GeminiCLIEngine(stub(tmp_path, "gemini", out), model="gemini-2.5-flash")
    r = e.run(req(tmp_path, edit=True))
    assert r.tokens == 7 and extract_json(r.text)["summary"] == "hi"
    args = (tmp_path / "gemini.args").read_text()
    assert "--approval-mode auto_edit" in args and "-m gemini-2.5-flash" in args and "--output-format json" in args


def test_ollama_unreachable_is_unavailable(tmp_path):
    with pytest.raises(EngineUnavailable):
        OllamaEngine("http://127.0.0.1:9", "llama3.2:3b").run(req(tmp_path))


def test_extract_json_variants():
    assert extract_json('blah\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('text {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    with pytest.raises(Exception):
        extract_json("nothing")
