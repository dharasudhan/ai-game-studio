"""Seen-it capture (1.5.0): QA launches the game in a window and attaches screenshots to Gate 3."""
import os
import stat
from pathlib import Path

from studio import godot


def _fake_godot(tmp_path, writes=True):
    f = tmp_path / "godot"
    body = 'for a in "$@"; do case "$a" in --out=*) d="${a#--out=}"; mkdir -p "$d"; '
    body += ('printf "\\x89PNG" > "$d/shot_01.png"; printf "\\x89PNG" > "$d/shot_02.png";; esac; done\n' if writes
             else ';; esac; done\n')
    f.write_text("#!/bin/sh\n" + body + "echo RESULT total=1 failures=0\nexit 0\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


def test_capture_skips_without_godot(tmp_path):
    ok, detail, files = godot.capture_screens(tmp_path, None, tmp_path / "s")
    assert ok is None and files == []


def test_capture_saves_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    wt = tmp_path / "game"
    wt.mkdir()
    ok, detail, files = godot.capture_screens(wt, _fake_godot(tmp_path), tmp_path / "shots")
    assert ok is True and len(files) == 2
    assert not (wt / ".studio_capture.gd").exists()


def test_capture_fails_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    wt = tmp_path / "game"
    wt.mkdir()
    ok, _, files = godot.capture_screens(wt, _fake_godot(tmp_path, writes=False), tmp_path / "shots")
    assert ok is False and files == []


def test_run_qa_reports_seen_it_check(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    wt = tmp_path / "game"
    wt.mkdir()
    (wt / "project.godot").write_text("")
    rep = godot.run_qa(wt, [], _fake_godot(tmp_path), shots_dir=tmp_path / "shots")
    names = [c["name"] for c in rep.checks]
    assert any(n.startswith("seen-it") for n in names) and len(rep.shots) == 2
