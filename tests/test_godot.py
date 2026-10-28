"""Real Godot 4.7 headless checks on the project template (skipped when GODOT_BIN is not available)."""
import os
import shutil
from pathlib import Path

import pytest

from studio.godot import run_qa
from studio.workflow import TEMPLATE, fill_template

GODOT = os.environ.get("GODOT_BIN")
pytestmark = pytest.mark.skipif(not GODOT or not Path(GODOT).exists(), reason="GODOT_BIN not set")


def make(tmp_path):
    p = tmp_path / "g"
    shutil.copytree(TEMPLATE, p)
    fill_template(p, {"{{TITLE}}": "T", "{{SLUG_ID}}": "t", "{{SLUG}}": "t", "{{PACKAGE}}": "com.ottranstudios.t",
                      "{{STUDIO}}": "Ottran Studios", "{{CONTACT}}": "ottranstudios@gmail.com",
                      "{{WEBSITE}}": "https://ottranstudios.com", "{{PRIVACY_URL}}": "https://ottranstudios.com/t/privacy-policy.html",
                      "{{TARGET_SDK}}": "36"})
    return p


def test_template_passes(tmp_path):
    rep = run_qa(make(tmp_path), [], GODOT)
    assert rep.passed, rep.markdown()
    assert any("6 run, 0 failed" in c["name"] for c in rep.checks)   # smoke + Ottran template rules (intro, legal)


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
