"""Launch-readiness audit (standing rule, Murali 2026-10-25): before EVERY closed-test or production upload,
QA + Compliance audit performance, device compatibility, Google Play policy and compliance, and produce a PDF with
blockers first. In this studio the audit is a workflow step: the Gate 5 (store release) approval refuses to pass
while the latest audit for the build has blockers or is missing.

Deterministic checks (this file) cover what code can verify in the repo; the QA agent adds judgment items
(performance, device compatibility, policy, compliance) through the `qa.launch_audit` task.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .pdfgen import markdown_to_pdf
from .secretscan import scan

VERDICTS = ("FAIL", "TODO", "PASS")
Fetcher = Callable[[str], tuple[int, str]]

# The compliance checklist every game goes through (studio/compliance.md in the Hark edition).
COMPLIANCE_CHECKLIST = [
    ("compliance", "Target audience 13+ (not Families) unless the game is deliberately for kids"),
    ("compliance", "AdMob max ad content rating G; test ad IDs until just before production"),
    ("compliance", "GDPR/ePrivacy: Google UMP consent before any ad request; consent re-openable in Settings"),
    ("policy", "Play Console: Advertising ID declared (Yes: Advertising, Analytics) when the AdMob SDK is included"),
    ("policy", "Data safety form matches the SDK list (AdMob, Play Billing) and the privacy policy"),
    ("policy", "Privacy policy URL hosted and naming the FINAL package id (redeploy after a package change)"),
    ("policy", "EU DSA trader status, public address, phone and email set in Play Console"),
    ("compliance", "Asset licences checked; CREDITS.md plus in-game credits (fonts OFL, CC BY attributions)"),
    ("policy", "IARC content rating questionnaire answered honestly"),
    ("policy", "Personal developer account: 12 testers opted in for 14 days on a closed test before production "
               "(Google Group tester list)"),
    ("policy", "Release AAB signed with the upload key, versionCode bumped, target SDK 36"),
    ("policy", "Store screenshots exported as JPEG (the Play asset picker rejected PNG), feature graphic 1024x500"),
    ("policy", "Plan for review time: Google review can take up to 7 days"),
]


def _default_fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-game-studio-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(400_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""


def read_preset(repo: Path) -> dict:
    """Key values of the Android export preset (export_presets.cfg)."""
    p = Path(repo) / "export_presets.cfg"
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(errors="ignore").splitlines():
        m = re.match(r'^([\w/.\-]+)=(.*)$', line.strip())
        if m:
            k, v = m.group(1), m.group(2).strip().strip('"')
            out.setdefault(k, v)
    return out


def _item(area: str, check: str, verdict: str, blocker: bool = False, fix: str = "", source: str = "auto") -> dict:
    return {"area": area, "check": check, "verdict": verdict, "blocker": bool(blocker and verdict != "PASS"),
            "fix": fix, "source": source}


def deterministic_checks(repo: Path, slug: str, s: dict, release_qa: str = "", released_code: int = 0,
                         fetch: Fetcher | None = None) -> list[dict]:
    repo = Path(repo)
    items: list[dict] = []
    pre = read_preset(repo)
    prefix = (s.get("package_prefix") or "com.ottranstudios").strip(".")
    want_pkg = f"{prefix}.{slug.replace('-', '_')}"
    pkg = pre.get("package/unique_name", "")
    if not pkg:
        items.append(_item("policy", "Android package id set", "FAIL", True, "Set package/unique_name in export_presets.cfg"))
    elif pkg.startswith(prefix + "."):
        items.append(_item("policy", f"Package id {pkg} uses the studio prefix {prefix}", "PASS"))
    else:
        items.append(_item("policy", f"Package id {pkg} uses the studio prefix {prefix}", "FAIL", True,
                           f"Rename to {want_pkg} BEFORE the first upload (a published package id can never change)"))
    try:
        code = int(pre.get("version/code") or 0)
    except ValueError:
        code = 0
    if code > int(released_code or 0):
        items.append(_item("policy", f"versionCode {code} is higher than the last released {released_code}", "PASS"))
    else:
        items.append(_item("policy", f"versionCode {code} is higher than the last released {released_code}", "FAIL", True,
                           "Bump version/code in export_presets.cfg (Play rejects a reused versionCode)"))
    target = str(s.get("play_target_sdk") or "36")
    t = pre.get("gradle_build/target_sdk", "")
    items.append(_item("device", f"Target SDK {t or '(Godot default)'} meets Play's required {target}",
                       "PASS" if t == target else "FAIL", True, f"Set gradle_build/target_sdk={target}"))
    arm64 = pre.get("architectures/arm64-v8a", "false") == "true"
    items.append(_item("device", "64-bit (arm64-v8a) build enabled", "PASS" if arm64 else "FAIL", True,
                       "Enable architectures/arm64-v8a"))
    leaked = [k for k in ("keystore/release_password", "keystore/release_user", "keystore/release")
              if pre.get(k)]
    items.append(_item("policy", "No release keystore path/user/password inside export_presets.cfg",
                       "FAIL" if leaked else "PASS", True,
                       "Clear them; use GODOT_ANDROID_KEYSTORE_RELEASE_* env vars on your Mac instead"))
    found = scan(repo)
    items.append(_item("compliance", "Secret scan: no keys, passwords, keystores or builds tracked in the repo",
                       "FAIL" if found else "PASS", True,
                       "Remove: " + ", ".join(f"{f['file']} ({f['kind']})" for f in found[:6])))
    intro = (repo / "addons" / "studio_intro" / "studio_intro.tscn").exists()
    proj = (repo / "project.godot").read_text(errors="ignore") if (repo / "project.godot").exists() else ""
    wired = "addons/studio_intro/studio_intro.tscn" in proj and "StudioLoader" in proj
    items.append(_item("brand", f"{s.get('studio_name') or 'Studio'} intro + loading screen kit installed and wired",
                       "PASS" if intro and wired else "FAIL", True,
                       "Copy addons/studio_intro, main scene = studio_intro.tscn, autoload StudioLoader"))
    legal = {}
    lp = repo / "config" / "legal.json"
    if lp.exists():
        try:
            legal = json.loads(lp.read_text())
        except json.JSONDecodeError:
            legal = {}
    url = str(legal.get("privacy_policy_url") or "")
    if not url.startswith("https://"):
        items.append(_item("policy", "Privacy policy URL set in config/legal.json (https)", "FAIL", True,
                           "Host the policy (Gate 6) and put its URL in config/legal.json and the Play listing"))
    elif s.get("audit_fetch_privacy_policy", "1") != "1":
        items.append(_item("policy", f"Privacy policy at {url} names the package id {pkg or want_pkg}", "TODO", False,
                           "Open the URL and check the package id (automatic fetch is off in Settings)"))
    else:
        try:
            status, body = (fetch or _default_fetch)(url)
        except Exception as e:  # noqa: BLE001 - network problems become a TODO, never a crash
            status, body = 0, str(e)
        if status == 200 and (pkg or want_pkg) in body:
            items.append(_item("policy", f"Privacy policy at {url} is live and names {pkg or want_pkg}", "PASS"))
        elif status == 200:
            items.append(_item("policy", f"Privacy policy at {url} names the package id {pkg or want_pkg}", "FAIL", True,
                               "Redeploy the policy with the final package id (needs Gate 6)"))
        elif status in (404, 410):
            items.append(_item("policy", f"Privacy policy hosted at {url}", "FAIL", True, "Host it (Gate 6) before upload"))
        else:
            items.append(_item("policy", f"Privacy policy hosted at {url}", "TODO", False,
                               f"Could not verify (HTTP {status or 'error'}); check it by hand"))
    email = str(legal.get("contact_email") or "")
    want_email = s.get("contact_email") or ""
    items.append(_item("policy", f"Contact email in the game is the studio address {want_email}",
                       "PASS" if email and email == want_email else "FAIL", False,
                       f"Set contact_email={want_email} in config/legal.json"))
    items.append(_item("compliance", "CREDITS.md lists every third-party asset and its licence",
                       "PASS" if (repo / "CREDITS.md").exists() else "FAIL", True, "Add CREDITS.md"))
    src = " ".join(p.read_text(errors="ignore") for p in list(repo.rglob("*.gd"))[:400]
                   if ".godot" not in p.parts and "addons" not in p.parts)
    uses_ads = bool(re.search(r"(?i)admob|MobileAds|ad_unit", src))
    if uses_ads:
        consent = bool(re.search(r"(?i)\bump\b|consentinformation|consent_form|request_consent", src))
        items.append(_item("compliance", "Ads present: Google UMP consent requested before ads", "PASS" if consent else "FAIL",
                           True, "Request UMP consent before loading any ad; add a Privacy options entry in Settings"))
    pngs = [str(p.relative_to(repo)) for d in ("store", "marketing") for p in (repo / d).rglob("*.png")
            if (repo / d).exists() and "screenshot" in str(p).lower()]
    items.append(_item("policy", "Store screenshots are JPEG", "FAIL" if pngs else "PASS", False,
                       "Export JPEG copies (the Play asset picker rejected PNG): " + ", ".join(pngs[:4])))
    if "QA PASSED" in release_qa:
        items.append(_item("performance", "Release QA: headless import, unit tests and smoke run passed", "PASS"))
    elif "QA FAILED" in release_qa:
        items.append(_item("performance", "Release QA: headless import, unit tests and smoke run passed", "FAIL", True,
                           "Fix the failing QA checks first"))
    else:
        items.append(_item("performance", "Release QA ran on main", "TODO", False, "Run QA with Godot installed"))
    for area, check in COMPLIANCE_CHECKLIST:
        items.append(_item(area, check, "TODO", False, "Confirm in Play Console / the build, then tick it off", "checklist"))
    return items


def merge_agent_items(items: list[dict], agent: dict | None) -> list[dict]:
    for it in (agent or {}).get("items") or []:
        if not isinstance(it, dict) or not it.get("check"):
            continue
        v = str(it.get("verdict", "TODO")).upper()
        v = v if v in VERDICTS else "TODO"
        items.append(_item(str(it.get("area", "review"))[:40], str(it["check"])[:300], v,
                           bool(it.get("blocker")) and v == "FAIL", str(it.get("fix", ""))[:500], "agent"))
    return items


def summarize(items: list[dict]) -> dict:
    blockers = [i for i in items if i["blocker"]]
    todos = [i for i in items if i["verdict"] == "TODO"]
    return {"blockers": len(blockers), "todos": len(todos), "fails": sum(1 for i in items if i["verdict"] == "FAIL"),
            "verdict": "BLOCKED" if blockers else "READY"}


def render_markdown(title: str, version: str, code: int, items: list[dict], agent_summary: str = "") -> str:
    sm = summarize(items)
    order = sorted(items, key=lambda i: (not i["blocker"], VERDICTS.index(i["verdict"]), i["area"]))
    lines = [f"# Launch-readiness audit: {title} v{version} (versionCode {code})",
             f"Date: {time.strftime('%Y-%m-%d %H:%M')}  -  Verdict: **{sm['verdict']}**  -  "
             f"{sm['blockers']} blocker(s), {sm['fails']} fail(s), {sm['todos']} to check by hand", ""]
    if agent_summary:
        lines += ["QA/Compliance review: " + agent_summary, ""]
    lines.append("## Blockers (fix before any upload)")
    bl = [i for i in order if i["blocker"]]
    lines += [f"- [{i['area']}] {i['check']} -> FIX: {i['fix']}" for i in bl] or ["- none"]
    lines.append("## Other findings")
    lines += [f"- {i['verdict']} [{i['area']}] {i['check']}" + (f" -> {i['fix']}" if i["fix"] and i["verdict"] != "PASS" else "")
              for i in order if not i["blocker"]]
    lines += ["", "Gate 5 (store upload) stays closed while any blocker is open. Not legal advice."]
    return "\n".join(lines)


def write_pdf(md: str, path: Path, title: str) -> Path:
    return markdown_to_pdf(md, path, title)
