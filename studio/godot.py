"""Godot helpers: locate the binary, run headless tests + smoke, optional Android (Gradle) export."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TEXT_EXT = {".gd", ".tscn", ".tres", ".godot", ".cfg", ".md", ".json", ".txt", ".svg", ".gdshader"}
CONFLICT = re.compile(r"^(<<<<<<< |>>>>>>> |=======$)", re.M)


def find_godot(configured: str = "") -> str | None:
    for c in (configured, os.environ.get("GODOT_BIN", "")):
        if c and (shutil.which(c) or Path(c).exists()):
            return shutil.which(c) or c
    for name in ("godot", "godot4", "Godot"):
        if shutil.which(name):
            return shutil.which(name)
    for p in sorted(glob.glob("/Applications/Godot*.app/Contents/MacOS/Godot")):
        return p
    return None


@dataclass
class QAReport:
    passed: bool = True
    godot: str | None = None
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, ok: bool | None, detail: str = "") -> None:
        # ok=None means skipped (does not fail the run)
        self.checks.append({"name": name, "status": "skip" if ok is None else ("pass" if ok else "fail"),
                            "detail": detail[-4000:]})
        if ok is False:
            self.passed = False

    def markdown(self) -> str:
        lines = [f"**QA {'PASSED' if self.passed else 'FAILED'}** (godot: {self.godot or 'not found'})", ""]
        for c in self.checks:
            icon = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[c["status"]]
            lines.append(f"- {icon} {c['name']}")
            if c["detail"] and c["status"] != "pass":
                lines.append("```\n" + c["detail"][-1500:] + "\n```")
        return "\n".join(lines)


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"timeout after {timeout}s\n{e.stdout or ''}"


def static_checks(wt: Path, changed: list[str], rep: QAReport) -> None:
    rep.add("project.godot present", (wt / "project.godot").exists())
    bad = []
    for f in changed:
        p = wt / f
        if p.suffix in TEXT_EXT and p.exists():
            if CONFLICT.search(p.read_text(errors="ignore")):
                bad.append(f)
    rep.add("no merge-conflict markers", not bad, ", ".join(bad))
    forbidden = [f for f in changed if f.startswith((".godot/", "android/", "build/")) or f.endswith((".keystore", ".jks"))]
    rep.add("no generated/secret files committed", not forbidden, ", ".join(forbidden))


def run_qa(wt: Path, changed: list[str], godot_bin: str | None, timeout: int = 300) -> QAReport:
    rep = QAReport(godot=godot_bin)
    static_checks(wt, changed, rep)
    if not godot_bin:
        rep.add("godot headless tests", None, "Godot not found; install Godot 4.3 or set godot_bin in Settings")
        return rep
    code, out = _run([godot_bin, "--headless", "--path", ".", "--import"], wt, timeout)
    rep.add("godot import", code == 0 and "SCRIPT ERROR" not in out, out if code else "")
    if (wt / "tests" / "run_tests.gd").exists():
        code, out = _run([godot_bin, "--headless", "--path", ".", "-s", "res://tests/run_tests.gd"], wt, timeout)
        m = re.search(r"RESULT total=(\d+) failures=(\d+)", out)
        ok = code == 0 and bool(m) and m.group(2) == "0" and "SCRIPT ERROR" not in out
        rep.add(f"godot unit tests ({m.group(1)} run, {m.group(2)} failed)" if m else "godot unit tests", ok, out)
    else:
        rep.add("godot unit tests", None, "tests/run_tests.gd missing")
    code, out = _run([godot_bin, "--headless", "--path", ".", "--quit-after", "120"], wt, timeout)
    rep.add("smoke: main scene runs 120 frames", code == 0 and "SCRIPT ERROR" not in out, out)
    return rep


def android_env_ready() -> tuple[bool, str]:
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk or not Path(sdk).exists():
        return False, "ANDROID_HOME not set (see README: Android SDK)"
    if not os.environ.get("JAVA_HOME") and not shutil.which("java"):
        return False, "JDK 17 not found (JAVA_HOME)"
    return True, sdk


def android_export(repo: Path, godot_bin: str | None, out_dir: Path, timeout: int = 1800) -> tuple[bool | None, str]:
    """Debug Gradle export of the 'Android' preset. Returns (ok|None=skipped, detail)."""
    if not godot_bin:
        return None, "Godot not found"
    ready, why = android_env_ready()
    if not ready:
        return None, why
    if not (repo / "export_presets.cfg").exists():
        return None, "export_presets.cfg missing"
    out_dir.mkdir(parents=True, exist_ok=True)
    apk = out_dir / "game-debug.apk"
    code, out = _run([godot_bin, "--headless", "--path", ".", "--install-android-build-template",
                      "--export-debug", "Android", str(apk)], repo, timeout)
    ok = code == 0 and apk.exists()
    return ok, (f"APK: {apk}\n" if ok else "") + out[-3000:]
