"""Real Godot 4.3 headless checks on the project template (skipped when GODOT_BIN is not available)."""
import os
import shutil
from pathlib import Path

import pytest

from studio.godot import run_qa
from studio.workflow import TEMPLATE

GODOT = os.environ.get("GODOT_BIN")
pytestmark = pytest.mark.skipif(not GODOT or not Path(GODOT).exists(), reason="GODOT_BIN not set")


def make(tmp_path):
    p = tmp_path / "g"
    shutil.copytree(TEMPLATE, p)
    for f in p.rglob("*"):
        if f.is_file() and f.suffix in {".godot", ".gd", ".cfg"}:
            f.write_text(f.read_text().replace("{{TITLE}}", "T").replace("{{SLUG_ID}}", "t"))
    return p


def test_template_passes(tmp_path):
    rep = run_qa(make(tmp_path), [], GODOT)
    assert rep.passed, rep.markdown()
    assert any("2 run, 0 failed" in c["name"] for c in rep.checks)


def test_failing_test_fails(tmp_path):
    p = make(tmp_path)
    (p / "tests" / "test_bad.gd").write_text("extends RefCounted\n\nfunc test_nope() -> bool:\n\treturn false\n")
    rep = run_qa(p, ["tests/test_bad.gd"], GODOT)
    assert not rep.passed


def test_script_error_fails(tmp_path):
    p = make(tmp_path)
    (p / "scripts" / "main.gd").write_text("extends Node2D\n\nfunc _ready() -> void:\n\tvar x: int = \"oops\"\n")
    rep = run_qa(p, ["scripts/main.gd"], GODOT)
    assert not rep.passed
