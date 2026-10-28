"""Prompt assembly and reply parsing.

Role personas live in prompts/<role>.md (edit freely; re-read on every run). The output contract for
each task lives here because the studio code depends on those keys.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROLES = ["producer", "designer", "engineer", "artist", "qa", "marketing", "analyst", "support", "bugfixer"]

CONTRACTS: dict[str, str] = {
    "designer.pitch": """Write ONE original game concept pitch for the owner's goal (mobile-first, Godot 4.7, small scope a solo
studio can ship in weeks). Cover: hook, core loop, target player, art direction, session length, monetization
(fair, no dark patterns), scope risks, and why it can stand out.
Reply JSON: {"title": str, "logline": str, "pitch_markdown": str}""",
    "producer.plan": """Turn the approved concept into a milestone plan: 2-5 milestones, each with 1-6 small tickets
(each ticket doable in one focused agent session). Assign each ticket to exactly one agent of:
engineer (GDScript code + tests), artist (placeholder/procedural art, UI, icons, asset prompts),
designer (GDD, levels, economy docs in docs/), qa (extra tests), marketing (drafts in marketing/),
analyst (only if data exists). First milestone = smallest playable core loop.
Reply JSON: {"milestones": [{"title": str, "goal": str, "tickets": [{"agent": str, "title": str, "description": str}]}]}""",
    "ticket.work": """Do this ticket inside the current directory (a Godot 4.7 project on its own git branch).
Edit/create files directly if your tools allow it; otherwise return them in "files" (full file contents,
paths relative to the project root). Do NOT run git. Add or update tests in tests/test_*.gd for code.
For an unfamiliar feature, first look at how actively maintained, clearly licensed open-source projects solve it
and say in "summary" which design you followed (credit reused ideas/code in CREDITS.md; never copy
licence-incompatible or unknown-source code).
If the work would need money (assets, tools, ads) or anything public, do not do it; list it in
"spend_requests" / "public_actions" instead.
Reply JSON: {"summary": str, "files": [{"path": str, "content": str}],
 "spend_requests": [{"amount": number, "currency": str, "vendor": str, "reason": str}],
 "public_actions": [{"channel": str, "content": str}]}""",
    "qa.review": """Review the change (diff + automated results below) like a strict QA lead for a mobile game.
Fail it for broken logic, missing tests for new code, crashes, or anything outside the ticket's scope.
Reply JSON: {"verdict": "pass"|"fail", "summary": str, "bugs": [{"title": str, "severity": "low"|"med"|"high", "details": str}]}""",
    "producer.standup": """Write today's standup for the owner from the board below: done since last standup, in progress,
blocked/waiting on owner approvals (most important first), and the next 3 actions. Be brief.
Reply JSON: {"standup_markdown": str}""",
    "marketing.release_kit": """Prepare the release kit as DRAFTS (nothing is posted or uploaded by you): Play Store listing
(title <=30 chars, short description <=80 chars, full description, tags/category, content rating notes,
privacy notes, the studio contact email and website from the context), a screenshots plan (5-8 shots with
captions; screenshots are exported as JPEG because the Play asset picker rejected PNG; feature graphic
1024x500), a 30s trailer script with shot list, and 2-4 social post drafts. Each social post goes into
"public_actions" so the owner can approve it (Gate 6).
Reply JSON: {"store_listing_markdown": str, "screenshots_plan_markdown": str, "trailer_script_markdown": str,
 "public_actions": [{"channel": str, "content": str}]}""",
    "qa.launch_audit": """You are QA + Compliance running the launch-readiness audit that must pass before EVERY closed-test or
production upload. The automated checks above are done; add what needs judgment: performance (startup time,
FPS, memory, AAB size, battery/thermal), device compatibility (screen sizes/aspect ratios, orientation,
renderer, 16 KB page alignment), Google Play policy (permissions + declarations incl. Advertising ID, target
audience 13+, ads policy, Billing, Data safety, IARC, listing metadata, DSA trader, the personal-account
closed-test rule of 12 testers x 14 days; for a game whose Platform is not android, check that
platform's store rules from its platform track instead) and compliance (GDPR/UMP consent, COPPA/Families, asset licences
and credits, IAP terms). Read the repository; do not edit anything. Mark verdict PASS / FAIL / TODO (cannot be
verified from the repo); set blocker=true only for a FAIL that must be fixed before upload. Not legal advice.
Reply JSON: {"summary": str, "items": [{"area": "performance"|"device"|"policy"|"compliance", "check": str,
 "verdict": "PASS"|"FAIL"|"TODO", "blocker": bool, "fix": str}]}""",
    "marketing.public_redraft": """The owner rejected this public post draft. Redraft it using the feedback.
Reply JSON: {"public_actions": [{"channel": str, "content": str}]}""",
    "analyst.analyze": """Analyse the exported data the owner dropped in (reviews, crashes, revenue, analytics). Give the
3-5 most important findings with numbers, then concrete next steps. If work is warranted, propose ONE
follow-up milestone with small tickets (same agent names as the producer uses).
Reply JSON: {"report_markdown": str, "proposed_milestone": {"title": str, "goal": str, "tickets": [{"agent": str, "title": str, "description": str}]} | null}""",
    "support.triage": """Triage the player feedback items below (JSON between the markers). For EACH item return:
category: one of bug | crash | feature_request | praise | billing | ads | abuse | other
sentiment: positive | neutral | negative;  severity: low | med | high | critical (crash on launch, data or
purchase loss = critical; most bugs = med); summary: one neutral line (no personal data);
group_label: 2-5 words naming the underlying issue so similar reports group together;
needs_reply: true unless it is abuse/spam or has nothing to answer;
reply_draft: a short, warm, honest reply in the player's language (no promises of dates, no blame, never ask
for passwords or card numbers, billing: point to Google Play refunds + ask for the order number).
These replies are DRAFTS: the owner approves each one at Gate 6 and posts it himself.
Reply JSON: {"items": [{"id": int, "category": str, "sentiment": str, "severity": str, "summary": str,
 "group_label": str, "needs_reply": bool, "reply_draft": str}]}""",
    "support.redraft_reply": """The owner rejected your reply draft to this player. Rewrite it using the owner's note.
Reply JSON: {"reply_draft": str}""",
    "support.fixed_replies": """These players reported a problem that is now fixed in the version named below. Write a short
follow-up reply for each ("fixed in vX - please update and tell us if it still happens"). Drafts only.
Reply JSON: {"replies": [{"id": int, "reply_draft": str}]}""",
    "bugfix.intake": """Turn these player reports (one grouped issue) into ONE bug ticket for the game repo. Use the repo file
list to guess where the bug lives. Write numbered repro steps a tester can follow, expected vs actual, and how
a headless GDScript test in tests/test_*.gd could reproduce it (or say why it cannot).
Reply JSON: {"title": str, "severity": "low"|"med"|"high"|"critical", "repro_steps": str, "expected": str,
 "actual": str, "suspected_area": str, "test_plan": str}""",
    "bugfix.fix": """Fix this bug inside the current directory (a Godot 4.7 project on its own git branch).
Work test-first: FIRST add a regression test tests/test_bug_<ticket id>_*.gd that fails on the current code
and passes after your fix (extends RefCounted; test_* methods return true on pass). Then make the smallest
fix that makes it pass without breaking other tests. Do NOT run git. Edit files directly if your tools allow
it; otherwise return full file contents in "files". If a test is impossible (pure visual/device issue), say why
in "no_test_reason". Money or public actions: list them in spend_requests / public_actions, never do them.
Reply JSON: {"summary": str, "root_cause": str, "regression_test": str, "no_test_reason": str,
 "files": [{"path": str, "content": str}], "spend_requests": [], "public_actions": []}""",
}

TASK_ROLE = {
    "designer.pitch": "designer", "producer.plan": "producer", "qa.review": "qa",
    "producer.standup": "producer", "marketing.release_kit": "marketing",
    "qa.launch_audit": """You are QA + Compliance running the launch-readiness audit that must pass before EVERY closed-test or
production upload. The automated checks above are done; add what needs judgment: performance (startup time,
FPS, memory, AAB size, battery/thermal), device compatibility (screen sizes/aspect ratios, orientation,
renderer, 16 KB page alignment), Google Play policy (permissions + declarations incl. Advertising ID, target
audience 13+, ads policy, Billing, Data safety, IARC, listing metadata, DSA trader, the personal-account
closed-test rule of 12 testers x 14 days) and compliance (GDPR/UMP consent, COPPA/Families, asset licences
and credits, IAP terms). Read the repository; do not edit anything. Mark verdict PASS / FAIL / TODO (cannot be
verified from the repo); set blocker=true only for a FAIL that must be fixed before upload. Not legal advice.
Reply JSON: {"summary": str, "items": [{"area": "performance"|"device"|"policy"|"compliance", "check": str,
 "verdict": "PASS"|"FAIL"|"TODO", "blocker": bool, "fix": str}]}""",
    "marketing.public_redraft": "marketing", "analyst.analyze": "analyst",
    "support.triage": "support", "support.redraft_reply": "support", "support.fixed_replies": "support",
    "bugfix.intake": "bugfixer", "bugfix.fix": "bugfixer", "qa.launch_audit": "qa",
}

# what "Run now" does per agent (shown in the Agents page)
RUN_NOW = {
    "producer": "Write a standup for the game now",
    "designer": "Pitch a new concept (game must be at concept stage)",
    "engineer": "Start the next open engineer ticket",
    "artist": "Start the next open artist ticket",
    "qa": "Headless QA health check on main (use Games > Actions for the launch audit)",
    "marketing": "Prepare the store release kit (Gate 5)",
    "analyst": "Re-analyse the files in the game's inbox",
    "support": "Scan feedback sources and triage new items",
    "bugfixer": "Take the next bug/crash group or open bug ticket",
}


PLATFORMS = ("android", "ios", "roblox", "web")
PLATFORM_DEFAULTS = Path(__file__).parent / "prompt_defaults" / "platforms"


def platform_track(prompts_dir: Path, platform: str) -> str:
    """The game's platform track (prompts/platforms/<p>.md, falling back to the shipped default)."""
    if platform not in PLATFORMS:
        return ""
    for p in (Path(prompts_dir) / "platforms" / f"{platform}.md", PLATFORM_DEFAULTS / f"{platform}.md"):
        if p.exists():
            return p.read_text()
    return ""


def load_role(prompts_dir: Path, role: str, platform: str = "") -> str:
    parts = []
    for name in ("_common.md", f"{role}.md"):
        p = prompts_dir / name
        if p.exists():
            parts.append(p.read_text())
    track = platform_track(prompts_dir, platform)
    if track:
        parts.append(track + "\nThis platform track overrides the Android/Godot defaults above where they differ.")
    return "\n\n".join(parts)


def build_prompt(prompts_dir: Path, role: str, task: str, context: str, feedback: list[str], platform: str = "") -> str:
    fb = "\n".join(f"- {n}" for n in feedback) or "- (none yet)"
    return (
        f"{load_role(prompts_dir, role, platform)}\n\n"
        f"# Owner feedback to respect (most recent first)\n{fb}\n\n"
        f"# Context\n{context.strip()}\n\n"
        f"# TASK: {task}\n{CONTRACTS[task]}\n\n"
        "End your reply with exactly one ```json fenced block containing the reply object. No other JSON blocks.\n"
    )


class ParseError(Exception):
    pass


def extract_json(text: str) -> dict:
    """Take the last ```json block, else the last balanced {...} object in the text."""
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text or "", re.S)
    for b in reversed(blocks):
        try:
            v = json.loads(b)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    s = text or ""
    end = s.rfind("}")
    while end != -1:
        depth = 0
        for i in range(end, -1, -1):
            if s[i] == "}":
                depth += 1
            elif s[i] == "{":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(s[i:end + 1])
                        if isinstance(v, dict):
                            return v
                    except json.JSONDecodeError:
                        pass
                    break
        end = s.rfind("}", 0, end)
    raise ParseError("reply did not contain a JSON object")
