"""First-run setup wizard backend: prerequisites, provider presets per role, keys, connection tests, studio identity.

The wizard UI lives in static/app.js (#setup). Everything here is plain functions + a mixin on Studio so the
API layer stays thin and the logic is testable without a browser.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import API_KEY_ENV
from .engines import PROVIDERS, check_provider, which
from .godot import find_godot
from .prompts import ROLES

Run = Callable[[list[str]], tuple[int, str]]

STEPS = ["welcome", "prereqs", "providers", "keys", "test", "identity", "accounts", "finish"]

ENGINEERING = ("engineer", "bugfixer", "qa")


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _first(s: str) -> str:
    return (s.strip().splitlines() or [""])[0][:160]


def check_prereqs(s: dict, run: Run | None = None, find: Callable[[str], str | None] | None = None,
                  env: dict | None = None) -> list[dict]:
    """Pass/fail for the Mac toolchain with how to fix each. `run`/`find`/`env` are injectable for tests."""
    run = run or _run
    find = find or which
    env = os.environ if env is None else env
    out: list[dict] = []

    def add(id_: str, label: str, ok: bool, detail: str, fix: str, required: bool = True, version: str = "") -> None:
        out.append({"id": id_, "label": label, "ok": bool(ok), "required": required, "detail": detail,
                    "version": version, "fix": "" if ok else fix})

    v = sys.version_info
    add("python", "Python 3.11+", v >= (3, 11), f"Python {v.major}.{v.minor}.{v.micro}",
        "brew install python@3.12, then re-run ./setup.sh", version=f"{v.major}.{v.minor}.{v.micro}")

    gd = s.get("godot_bin") or ""
    godot = find_godot(gd) if find is which else (find(gd or "godot") or None)
    if godot:
        code, txt = run([godot, "--version"])
        ver = _first(txt)
        add("godot", "Godot 4.7.x", code == 0 and ver.startswith("4.7"), f"{godot}: {ver or 'no version output'}",
            "Install Godot 4.7.2 stable (macOS) from https://godotengine.org/download/macos/ and move Godot.app to "
            "/Applications (or set godot_bin in Settings). Older 4.3 builds hit Android bugs.", version=ver)
    else:
        add("godot", "Godot 4.7.x", False, "not found",
            "Download Godot 4.7.2 stable for macOS from https://godotengine.org/download/macos/, move Godot.app to "
            "/Applications and open it once (Gatekeeper). Or set godot_bin in Settings.")

    sdk = s.get("android_sdk_path") or env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT") or ""
    sdk_ok = bool(sdk) and Path(sdk, "platform-tools").exists()
    add("android_sdk", "Android SDK (platform-tools, build-tools)", sdk_ok, sdk or "ANDROID_HOME not set",
        "brew install --cask android-commandlinetools, then sdkmanager --sdk_root=$HOME/Library/Android/sdk "
        "\"platform-tools\" \"build-tools;35.0.1\" \"platforms;android-35\" \"platforms;android-36\" \"cmdline-tools;latest\" "
        "\"cmake;3.10.2.4988404\" \"ndk;28.1.13356709\" (Godot 4.7 docs + API 36 for Play's target SDK); "
        "set ANDROID_HOME=$HOME/Library/Android/sdk (or android_sdk_path in Settings).", required=False)

    jh = s.get("java_home") or env.get("JAVA_HOME") or ""
    java = str(Path(jh, "bin", "java")) if jh else (find("java") or "")
    if java and (Path(java).exists() or find("java")):
        code, txt = run([java, "-version"])
        m = re.search(r'version "(\d+)', txt)
        major = m.group(1) if m else "?"
        add("jdk", "JDK 17 (Android export)", code == 0 and major == "17", f"{java}: Java {major}",
            "brew install --cask temurin@17 and set JAVA_HOME=$(/usr/libexec/java_home -v 17)", required=False,
            version=major)
    else:
        add("jdk", "JDK 17 (Android export)", False, "java not found",
            "brew install --cask temurin@17 and set JAVA_HOME=$(/usr/libexec/java_home -v 17)", required=False)

    g = find("git")
    code, txt = run([g, "--version"]) if g else (1, "")
    add("git", "git", bool(g) and code == 0, _first(txt) or "not found", "xcode-select --install (or brew install git)",
        version=_first(txt))

    gh = find("gh")
    if gh:
        code, txt = run([gh, "--version"])
        acode, atxt = run([gh, "auth", "status"])
        add("gh", "GitHub CLI (gh), signed in", code == 0 and acode == 0,
            _first(txt) + ("; signed in" if acode == 0 else "; not signed in"),
            "Run `gh auth login` (GitHub.com, HTTPS). Game repos are PRIVATE; the studio never pushes by itself.",
            required=False, version=_first(txt))
    else:
        add("gh", "GitHub CLI (gh), signed in", False, "not found",
            "brew install gh && gh auth login. Used by you to push private game repos.", required=False)
    return out


# ------------------------------------------------------------------ presets
PRESETS: dict[str, dict] = {
    "google_pro": {"label": "All Google AI Pro",
                   "blurb": "Every role on Antigravity CLI with your AI Pro login. No API bills.",
                   "providers": ["agy"]},
    "claude_eng": {"label": "Claude for engineering + Gemini for the rest",
                   "blurb": "Engineer, Bug Fixer and QA on Claude (Claude Code CLI if installed, else the Anthropic API); "
                            "everyone else on Antigravity (AI Pro).",
                   "providers": ["claude_code|anthropic", "agy"]},
    "local_only": {"label": "Local only (Ollama)",
                   "blurb": "Everything on your Mac with Ollama + Qwen2.5-Coder 7B. Free and private, slower, weaker "
                            "at big code changes.", "providers": ["ollama"]},
    "mixed": {"label": "Mixed",
              "blurb": "Claude for code, Codex/OpenAI for QA review, Gemini API (free tier) for Support and Analyst, "
                       "Antigravity for planning, design, art and marketing. A starting point: edit any row.",
              "providers": ["claude_code|anthropic", "codex|openai", "genai", "agy"]},
}


def preset_roles(preset: str, have_bin: Callable[[str], bool] | None = None) -> dict[str, dict]:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}' (one of {', '.join(PRESETS)})")
    have = have_bin or (lambda b: bool(which(b)))
    claude = {"engine": "claude_code", "model": "claude-sonnet-5-5"} if have("claude") else \
        {"engine": "anthropic", "model": "claude-sonnet-5-5"}
    if preset == "google_pro":
        return {r: {"engine": "agy", "model": ""} for r in ROLES}
    if preset == "claude_eng":
        return {r: (dict(claude) if r in ENGINEERING else {"engine": "agy", "model": ""}) for r in ROLES}
    if preset == "local_only":
        return {r: {"engine": "ollama", "model": "qwen2.5-coder:7b"} for r in ROLES}
    qa = {"engine": "codex", "model": ""} if have("codex") else {"engine": "openai", "model": "gpt-6.1-terra"}
    out = {}
    for r in ROLES:
        if r in ("engineer", "bugfixer"):
            out[r] = dict(claude)
        elif r == "qa":
            out[r] = dict(qa)
        elif r in ("support", "analyst"):
            out[r] = {"engine": "genai", "model": "gemini-3.8-flash"}
        else:
            out[r] = {"engine": "agy", "model": ""}
    return out


PKG_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s]*)?$")


def validate_identity(d: dict) -> dict:
    name = str(d.get("studio_name", "")).strip()
    pkg = str(d.get("package_prefix", "")).strip().strip(".").lower()
    email = str(d.get("contact_email", "")).strip()
    site = str(d.get("studio_website", "")).strip().rstrip("/")
    owner = str(d.get("github_owner", "")).strip()
    acct = str(d.get("play_account_type", "personal")).strip() or "personal"
    if not 2 <= len(name) <= 60:
        raise ValueError("studio name: 2 to 60 characters")
    if not PKG_RE.match(pkg) or pkg.startswith("com.studio"):
        raise ValueError("package prefix: reverse-domain like com.ottranstudios (lowercase, dots; not com.studio)")
    if not EMAIL_RE.match(email):
        raise ValueError("contact email looks wrong")
    if site and not URL_RE.match(site):
        raise ValueError("website must start with https://")
    if owner and not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        raise ValueError("GitHub owner: letters, digits and dashes only")
    if acct not in ("personal", "organization"):
        raise ValueError("Play account type: personal or organization")
    return {"studio_name": name, "package_prefix": pkg, "contact_email": email, "studio_website": site,
            "github_owner": owner, "play_account_type": acct}


class SetupMixin:
    """Mixed into Studio: wizard state, role config, keys and connection tests."""

    def roles_config(self) -> dict[str, dict]:
        return {a["name"]: {"engine": a["engine"], "model": a["model"]} for a in self.agents_brief()}

    def apply_roles(self, roles: dict) -> dict[str, dict]:
        if not isinstance(roles, dict) or not roles:
            raise ValueError("roles must be an object like {\"engineer\": {\"engine\": \"claude_code\", \"model\": \"...\"}}")
        for r, cfg in roles.items():
            if r not in ROLES:
                raise KeyError(f"agent {r} not found")
            cfg = cfg or {}
            self.set_agent(r, engine=str(cfg.get("engine", "")), model=str(cfg.get("model", "")))
        return self.roles_config()

    def apply_preset(self, preset: str, have_bin: Callable[[str], bool] | None = None) -> dict[str, dict]:
        roles = preset_roles(preset, have_bin)
        self.apply_roles(roles)
        self.db.set("setup_preset", preset)
        self.log(f"Setup: provider preset '{PRESETS[preset]['label']}' applied to all roles", agent="owner")
        return roles

    def used_providers(self) -> list[str]:
        s = self.db.settings()
        used = {a["engine"] or s.get("engine", "agy") for a in self.agents_brief()}
        return [p for p in PROVIDERS if p in used]

    def providers_info(self) -> list[dict]:
        s = self.db.settings()
        used = set(self.used_providers())
        out = []
        for p in PROVIDERS.values():
            if p.id == "fake":
                continue
            item = {"id": p.id, "label": p.label, "kind": p.kind, "agentic": p.agentic, "used": p.id in used,
                    "models": list(p.models), "default_model": s.get(p.model_setting, p.default_model) if p.model_setting else "",
                    "key_env": p.key_env, "cost_note": p.cost_note, "docs": p.docs, "install": p.install}
            if p.key_env:
                item["key"] = self.secrets.status(p.key_env)
            if p.bin_setting:
                b = s.get(p.bin_setting, "")
                item["binary"] = {"name": b, "found": bool(which(b))}
            out.append(item)
        return out

    def keys_status(self) -> dict:
        return {"keys": {k: self.secrets.status(k) for k in API_KEY_ENV},
                "backends": self.secrets.available_backends()}

    def save_key(self, name: str, value: str, backend: str) -> dict:
        if name not in API_KEY_ENV:
            raise ValueError(f"unknown key {name} (one of {', '.join(API_KEY_ENV)})")
        res = self.secrets.set(name, value, backend)
        self.log(f"Setup: {name} saved to {res['source']} ({res['masked']})", agent="owner")
        return res

    def test_connection(self, provider: str, deep: bool = False) -> dict:
        res = check_provider(provider, self.db.settings(), deep, self.secrets.get, self.fake,
                            getattr(self, "http_transport", None))
        self.log(f"Setup: test {provider}: {'OK' if res.get('ok') else 'FAILED'} - {res.get('detail', '')[:160]}",
                 agent="owner", level="info" if res.get("ok") else "warn")
        return res

    def save_identity(self, d: dict) -> dict:
        clean = validate_identity(d)
        for k, v in clean.items():
            self.db.set(k, v)
        self.log("Setup: studio identity saved (" + clean["studio_name"] + ", " + clean["package_prefix"] + ")", agent="owner")
        return clean

    def setup_state(self) -> dict:
        s = self.db.settings()
        return {"complete": s.get("setup_complete") == "1", "step": s.get("setup_step", "welcome"), "steps": STEPS,
                "presets": {k: {"label": v["label"], "blurb": v["blurb"]} for k, v in PRESETS.items()},
                "preset": s.get("setup_preset", ""), "roles": self.roles_config(), "default_engine": s.get("engine", "agy"),
                "identity": {k: s.get(k, "") for k in ("studio_name", "package_prefix", "contact_email", "studio_website",
                                                        "github_owner", "play_account_type")},
                "providers": self.providers_info(), "keys": self.keys_status()}

    def set_setup_step(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown step {step}")
        self.db.set("setup_step", step)

    def finish_setup(self) -> dict:
        s = self.db.settings()
        roles = self.roles_config()
        default = s.get("engine", "agy")
        lines = []
        for r, cfg in roles.items():
            eng = cfg["engine"] or default
            spec = PROVIDERS.get(eng)
            model = cfg["model"] or (s.get(spec.model_setting, "") if spec and spec.model_setting else "") or "default"
            lines.append({"role": r, "provider": eng, "label": spec.label if spec else eng, "model": model})
        keys = {k: v for k, v in self.keys_status()["keys"].items() if v["set"]}
        missing = []
        for eng in {ln["provider"] for ln in lines}:
            spec = PROVIDERS.get(eng)
            if spec and spec.key_env and not self.secrets.get(spec.key_env):
                missing.append(f"{spec.label} needs {spec.key_env}")
        self.db.set("setup_complete", "1")
        self.db.set("setup_step", "finish")
        self.log("Setup wizard finished", agent="owner")
        return {"roles": lines, "keys": keys, "missing": missing,
                "identity": {k: s.get(k, "") for k in ("studio_name", "package_prefix", "contact_email", "studio_website",
                                                        "github_owner", "play_account_type")}}
