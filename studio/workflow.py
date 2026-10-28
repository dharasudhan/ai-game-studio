"""The studio: agents, tickets, and the six approval gates.

Gate 1 concept  -> Gate 2 milestone plan -> tickets -> agent work on branch -> QA -> Gate 3 merge
Gate 4 any money spend (ledger)          Gate 5 store release           Gate 6 anything public

Nothing passes a gate without `approve()`; `reject(note)` stores the note as feedback for that agent
(it is included in every later prompt for that agent on that game) and sends the work back.
"""
from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import audit as audit_mod
from . import gitops
from .config import APP_ROOT, Paths, default_paths
from .db import DB, dumps, loads, now
from .engines import PROVIDERS, EngineError, EngineRequest, EngineResult, FakeEngine, build_engine
from .keystore import Keychain, SecretStore
from .feedback_flow import SupportMixin
from .godot import android_export, find_godot, run_qa
from .management import ManagementMixin
from .wizard import SetupMixin
from .notify import notify
from .prompts import PLATFORMS, ROLES, ParseError, build_prompt, extract_json

TEMPLATE = Path(__file__).parent / "templates" / "godot"
TEMPLATES = {"roblox": Path(__file__).parent / "templates" / "roblox"}
GATES = {1: "New game concept", 2: "Milestone plan", 3: "Code/build change -> main", 4: "Money spend",
         5: "Store release", 6: "Anything public"}
WORK_AGENTS = {"engineer", "artist", "designer", "qa", "marketing", "analyst"}


def fill_template(repo: Path, subs: dict[str, str]) -> None:
    """Replace {{PLACEHOLDERS}} in the template's text files (never inside addons/, which holds binaries)."""
    for f in Path(repo).rglob("*"):
        if f.is_file() and f.suffix in {".godot", ".gd", ".cfg", ".md", ".json", ".luau"} and "addons" not in f.relative_to(repo).parts:
            txt = f.read_text()
            for k, v in subs.items():
                txt = txt.replace(k, v)
            f.write_text(txt)


class AgentOutputError(Exception):
    """The agent replied, but not with something usable (retried like any failure)."""


def slugify(s: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return (s[:n].strip("-")) or "game"


class Studio(SupportMixin, ManagementMixin, SetupMixin):
    def __init__(self, paths: Paths | None = None, fake_engine: FakeEngine | None = None,
                 secrets: SecretStore | None = None):
        import os
        self.paths = paths or default_paths()
        self.paths.ensure()
        self.db = DB(self.paths.db)
        self.fake = fake_engine
        self._last_call = 0.0
        self.merge_lock = threading.Lock()
        self.throttle_lock = threading.Lock()
        self.tl = threading.local()   # per worker thread: engine name of the current run
        self.notifier = notify        # swappable in tests
        env_file = Path(os.environ.get("STUDIO_ENV_FILE") or (APP_ROOT / ".env"))
        no_kc = os.environ.get("STUDIO_NO_KEYCHAIN") == "1"
        self.secrets = secrets or SecretStore(env_file, Keychain(force=False) if no_kc else None)
        self.http_transport = None    # tests inject a fake HTTP transport for API providers
        self.seed_agents()

    # ------------------------------------------------------------------ utils
    def log(self, message: str, game_id: int | None = None, ticket_id: int | None = None,
            agent: str | None = None, level: str = "info") -> None:
        self.db.insert("events", game_id=game_id, ticket_id=ticket_id, agent=agent, level=level,
                       message=message[:4000], created_at=now())

    def notify(self, kind: str, title: str, message: str) -> str:
        try:
            res = self.notifier(self.db.settings(), kind, title, message)
        except Exception:  # noqa: BLE001
            res = "error"
        return res

    def game(self, gid: int) -> dict:
        g = self.db.one("SELECT * FROM games WHERE id=?", gid)
        if not g:
            raise KeyError(f"game {gid} not found")
        return g

    def ticket(self, tid: int) -> dict:
        t = self.db.one("SELECT * FROM tickets WHERE id=?", tid)
        if not t:
            raise KeyError(f"ticket {tid} not found")
        return t

    def set_ticket(self, tid: int, **cols: Any) -> None:
        self.db.update("tickets", tid, updated_at=now(), **cols)

    def set_game(self, gid: int, **cols: Any) -> None:
        self.db.update("games", gid, updated_at=now(), **cols)

    def enqueue(self, game_id: int | None, agent: str, kind: str, payload: dict | None = None,
                ticket_id: int | None = None, delay: float = 0, front: bool = False) -> int:
        """front=True (Run now / uploads) puts the job ahead of everything that is already waiting."""
        jid = self.db.insert("jobs", game_id=game_id, ticket_id=ticket_id, agent=agent, kind=kind,
                             payload_json=dumps(payload or {}), status="queued", attempts=0,
                             max_attempts=self.db.geti("max_attempts", 5), next_run_at=0 if front else now() + delay,
                             created_at=now(), updated_at=now())
        self.log(f"queued {kind}" + (f" for T#{ticket_id}" if ticket_id else ""), game_id, ticket_id, agent)
        return jid

    def add_doc(self, game_id: int, kind: str, title: str, content: str, agent: str) -> int:
        return self.db.insert("docs", game_id=game_id, kind=kind, title=title, content=content, agent=agent,
                              created_at=now())

    def create_approval(self, game_id: int, gate: int, kind: str, title: str, summary: str, payload: dict,
                        agent: str, ref_type: str | None = None, ref_id: int | None = None) -> int:
        aid = self.db.insert("approvals", game_id=game_id, gate=gate, kind=kind, title=title, summary=summary,
                             payload_json=dumps(payload), status="pending", agent=agent, ref_type=ref_type,
                             ref_id=ref_id, created_at=now())
        self.log(f"Gate {gate} ({GATES[gate]}) waiting for you: {title}", game_id, ref_id if ref_type == "ticket" else None, agent)
        self.notify("approvals", f"Gate {gate} waiting", title)
        return aid

    def feedback_for(self, game_id: int | None, agent: str, limit: int = 6) -> list[str]:
        rows = self.db.all("SELECT note, gate FROM feedback WHERE game_id IS ? AND agent=? ORDER BY id DESC LIMIT ?",
                           game_id, agent, limit)
        return [f"(gate {r['gate']}) {r['note']}" for r in rows]

    def scratch(self, game_id: int) -> Path:
        p = self.paths.scratch / f"game-{game_id}"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def latest_doc(self, game_id: int, kind: str) -> dict | None:
        return self.db.one("SELECT * FROM docs WHERE game_id=? AND kind=? ORDER BY id DESC LIMIT 1", game_id, kind)

    # ------------------------------------------------------------- engine call
    def engine_for(self, role: str, task: str):
        """Precedence: role_engines[task] > agent's own engine (Agents page) > chore engine for chore tasks >
        role_engines[role] > global engine. The agent's model/effort override the engine's model defaults."""
        s = self.db.settings()
        name = s.get("engine", "agy")
        over = loads(s.get("role_engines"), {}) or {}
        cfg = self.agent_cfg(role)
        chores = [t.strip() for t in s.get("chore_tasks", "").split(",") if t.strip()]
        if over.get(task):
            name = over[task]
        elif cfg.get("engine"):
            name = cfg["engine"]
        elif s.get("chore_engine") and task in chores:
            name = s["chore_engine"]
        elif over.get(role):
            name = over[role]
        s = dict(s)
        spec = PROVIDERS.get(name)
        if cfg.get("model") and spec and spec.model_setting:
            s[spec.model_setting] = cfg["model"]
        if cfg.get("effort") and name == "agy":
            s["agy_effort"] = cfg["effort"]
        if cfg.get("effort") and name == "openai":
            s["openai_effort"] = cfg["effort"]
        return build_engine(name, s, self.fake, self.secrets.get, self.http_transport)

    def _throttle(self) -> None:
        with self.throttle_lock:
            gap = self.db.geti("min_seconds_between_runs", 5)
            wait = self._last_call + gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def call_agent(self, job: dict, role: str, task: str, context: str, cwd: Path, edit: bool = False) -> dict:
        engine = self.engine_for(role, task)
        self.tl.engine = engine.name
        st = self.db.settings()
        ident = (f"Studio: {st.get('studio_name', '')} | package ids {st.get('package_prefix', '')}.<slug> | "
                 f"contact {st.get('contact_email', '')} | website {st.get('studio_website', '')}\n")
        g = self.db.one("SELECT platform FROM games WHERE id=?", job.get("game_id")) if job.get("game_id") else None
        platform = (g or {}).get("platform") or "android"
        ident += f"Platform: {platform}\n"
        prompt = build_prompt(self.paths.prompts, role, task, ident + context, self.feedback_for(job.get("game_id"), role),
                              platform)
        if not isinstance(engine, FakeEngine):
            self._throttle()
        rid = self.db.insert("runs", job_id=job["id"], game_id=job.get("game_id"), agent=role, task=task,
                             engine=engine.name, prompt=prompt, status="running", started_at=now())
        try:
            res: EngineResult = engine.run(EngineRequest(prompt=prompt, cwd=cwd, role=role, task=task, edit=edit,
                                                         timeout=self.db.geti("engine_timeout_seconds", 900)))
        except EngineError as e:
            self.db.update("runs", rid, status="error", error=f"{type(e).__name__}: {e}", finished_at=now())
            raise
        self.db.update("runs", rid, output=res.text, tokens=res.tokens, model=res.model, finished_at=now(), status="ok",
                       cost_usd=res.cost_usd)
        try:
            data = extract_json(res.text)
        except ParseError as e:
            self.db.update("runs", rid, status="bad_output", error=str(e))
            raise AgentOutputError(f"{role} reply had no JSON object") from e
        summary = next((str(data[k]) for k in ("summary", "title", "logline", "verdict") if data.get(k)), "")
        if not summary:
            summary = next((str(v) for v in data.values() if isinstance(v, str) and v), "")[:300]
        if not summary:
            summary = ", ".join(f"{len(v)} {k}" for k, v in data.items() if isinstance(v, list))
        self.db.update("runs", rid, summary=summary[:500])
        self.clear_engine_backoff(engine.name)
        data["_engine_agentic"] = getattr(engine, "agentic", False)
        return data

    # ----------------------------------------------------------- job dispatch
    def handle(self, job: dict) -> None:
        handler = {
            "designer.pitch": self.h_pitch, "producer.plan": self.h_plan, "ticket.work": self.h_ticket_work,
            "qa.verify": self.h_qa_verify, "producer.standup": self.h_standup, "qa.release_build": self.h_release_build,
            "marketing.release_kit": self.h_release_kit, "marketing.public_redraft": self.h_public_redraft,
            "analyst.analyze": self.h_analyze, "qa.health": self.h_qa_health,
            "support.ingest": self.h_support_ingest, "support.triage": self.h_support_triage,
            "support.redraft_reply": self.h_support_redraft, "support.fixed_replies": self.h_support_fixed_replies,
            "bugfix.intake": self.h_bugfix_intake, "qa.launch_audit": self.h_launch_audit,
        }.get(job["kind"])
        if not handler:
            raise AgentOutputError(f"unknown job kind {job['kind']}")
        handler(job, loads(job.get("payload_json"), {}) or {})

    def _side_requests(self, game_id: int, agent: str, data: dict, ticket_id: int | None = None) -> None:
        """Money and public actions never happen directly: they become Gate 4 / Gate 6 approvals."""
        for r in data.get("spend_requests") or []:
            try:
                amount = float(r.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            cur = r.get("currency") or self.db.get("currency", "EUR")
            lid = self.db.insert("ledger", game_id=game_id, description=str(r.get("reason", ""))[:500],
                                 vendor=str(r.get("vendor", ""))[:200], amount=amount, currency=cur,
                                 status="proposed", agent=agent, created_at=now())
            flags = self.spend_flags(amount)
            aid = self.create_approval(game_id, 4, "spend", f"Spend {amount:.2f} {cur} at {r.get('vendor', '?')}" + (f" ({', '.join(flags)})" if flags else ""),
                                       str(r.get("reason", "")), {"ledger_id": lid, **r}, agent, "ledger", lid)
            self.db.update("ledger", lid, approval_id=aid)
        for p in data.get("public_actions") or []:
            self.create_approval(game_id, 6, "public", f"Public post draft ({p.get('channel', '?')})",
                                 str(p.get("content", ""))[:300], {"channel": p.get("channel"), "content": p.get("content"),
                                                                   "ticket_id": ticket_id}, agent)

    # ------------------------------------------------------------------ games
    def new_game(self, goal: str, title: str = "", platform: str = "android") -> int:
        goal = (goal or "").strip()
        platform = (platform or "android").strip().lower()
        if not goal:
            raise ValueError("goal is required")
        if platform not in PLATFORMS:
            raise ValueError(f"platform must be one of {', '.join(PLATFORMS)}")
        gid = self.db.insert("games", slug=f"draft-{uuid.uuid4().hex[:12]}", title=title.strip() or "Untitled concept",
                             goal=goal, status="concept", platform=platform, repo_path="", created_at=now(), updated_at=now())
        self.log("New game requested: " + goal[:200], gid)
        self.enqueue(gid, "designer", "designer.pitch", {"title_hint": title})
        return gid

    def h_pitch(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        prev = [d["title"] for d in self.db.all("SELECT title FROM docs WHERE game_id=? AND kind='pitch'", g["id"])]
        ctx = f"Owner goal: {g['goal']}\n"
        if p.get("title_hint"):
            ctx += f"Working title idea from owner: {p['title_hint']}\n"
        if prev:
            ctx += "Rejected earlier pitches (do something different unless feedback says otherwise): " + ", ".join(prev) + "\n"
        if p.get("feedback"):
            ctx += f"Owner's rejection note on the last pitch: {p['feedback']}\n"
        data = self.call_agent(job, "designer", "designer.pitch", ctx, self.scratch(g["id"]))
        if not data.get("title") or not data.get("pitch_markdown"):
            raise AgentOutputError("pitch missing title/pitch_markdown")
        did = self.add_doc(g["id"], "pitch", data["title"], data["pitch_markdown"], "designer")
        self.create_approval(g["id"], 1, "concept", f"Concept: {data['title']}", data.get("logline", ""),
                             {"doc_id": did, "title": data["title"], "logline": data.get("logline", ""),
                              "markdown": data["pitch_markdown"]}, "designer", "doc", did)
        self.set_game(g["id"], status="concept_review", title=data["title"])

    def _create_repo(self, g: dict, title: str, concept_md: str) -> tuple[str, Path]:
        base = slugify(title)
        slug, n = base, 2
        while self.db.one("SELECT id FROM games WHERE slug=? AND id<>?", slug, g["id"]) or (self.paths.games / slug).exists():
            slug, n = f"{base}-{n}", n + 1
        repo = self.paths.games / slug
        shutil.copytree(TEMPLATES.get(g.get("platform") or "android", TEMPLATE), repo)
        st = self.db.settings()
        slug_id = slug.replace("-", "_")
        prefix = (st.get("package_prefix") or "com.ottranstudios").strip(".")
        site = (st.get("studio_website") or "").rstrip("/")
        subs = {"{{TITLE}}": title.replace('"', "'"), "{{SLUG_ID}}": slug_id, "{{SLUG}}": slug,
                "{{PACKAGE}}": f"{prefix}.{slug_id}", "{{STUDIO}}": st.get("studio_name") or "Ottran Studios",
                "{{CONTACT}}": st.get("contact_email") or "", "{{WEBSITE}}": site,
                "{{PRIVACY_URL}}": f"{site}/{slug}/privacy-policy.html" if site else "",
                "{{TARGET_SDK}}": st.get("play_target_sdk") or "36"}
        fill_template(repo, subs)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "concept.md").write_text(concept_md)
        gitops.init_repo(repo)
        self.set_game(g["id"], package=subs["{{PACKAGE}}"])
        return slug, repo

    # --------------------------------------------------------------- planning
    def h_plan(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        pitch = self.latest_doc(g["id"], "pitch_approved") or self.latest_doc(g["id"], "pitch")
        ctx = f"Game: {g['title']}\nOwner goal: {g['goal']}\n\nApproved concept:\n{(pitch or {}).get('content', '')[:8000]}\n"
        if p.get("feedback"):
            ctx += f"\nOwner's rejection note on the last plan: {p['feedback']}\n"
        data = self.call_agent(job, "producer", "producer.plan", ctx, self.scratch(g["id"]))
        ms = self._clean_milestones(data.get("milestones"))
        if not ms:
            raise AgentOutputError("plan has no milestones with tickets")
        self.create_approval(g["id"], 2, "plan", f"Milestone plan for {g['title']} ({len(ms)} milestones)",
                             self._plan_md(ms), {"milestones": ms, "source": "producer"}, "producer")
        self.set_game(g["id"], status="plan_review")

    @staticmethod
    def _clean_milestones(raw: Any) -> list[dict]:
        out = []
        for m in raw or []:
            if not isinstance(m, dict):
                continue
            ts = []
            for t in m.get("tickets") or []:
                if isinstance(t, dict) and t.get("title"):
                    agent = str(t.get("agent", "engineer")).lower().strip()
                    ts.append({"agent": agent if agent in WORK_AGENTS else "engineer", "title": str(t["title"])[:200],
                               "description": str(t.get("description", ""))[:4000]})
            if ts:
                out.append({"title": str(m.get("title", "Milestone"))[:200], "goal": str(m.get("goal", ""))[:1000], "tickets": ts})
        return out

    @staticmethod
    def _plan_md(ms: list[dict]) -> str:
        lines = []
        for i, m in enumerate(ms, 1):
            lines.append(f"## {i}. {m['title']}\n_{m['goal']}_")
            lines += [f"- [{t['agent']}] {t['title']}: {t['description']}" for t in m["tickets"]]
        return "\n".join(lines)

    def dispatch_next(self, gid: int) -> None:
        g = self.game(gid)
        for m in self.db.all("SELECT * FROM milestones WHERE game_id=? AND status<>'done' ORDER BY idx", gid):
            tickets = self.db.all("SELECT * FROM tickets WHERE milestone_id=?", m["id"])
            if tickets and all(t["status"] == "done" for t in tickets):
                self.db.update("milestones", m["id"], status="done")
                self.log(f"Milestone done: {m['title']}", gid, agent="producer")
                continue
            if m["status"] != "active":
                self.db.update("milestones", m["id"], status="active")
                self.log(f"Milestone started: {m['title']}", gid, agent="producer")
            for t in tickets:
                if t["status"] == "todo":
                    self.set_ticket(t["id"], status="queued")
                    self.enqueue(gid, t["agent"], "ticket.work", {}, ticket_id=t["id"])
            return
        if g["status"] == "in_production":
            self.set_game(gid, status="release_prep")
            self.log("All milestones done: preparing release build and store kit", gid, agent="producer")
            self.enqueue(gid, "qa", "qa.release_build", {})

    # ----------------------------------------------------------- ticket work
    def _wt(self, g: dict, t: dict) -> tuple[Path, Path, str]:
        repo = Path(g["repo_path"])
        branch = t["branch"] or f"{t['agent']}/t{t['id']}-{slugify(t['title'], 30)}"
        wt = Path(t["worktree"]) if t["worktree"] else self.paths.worktrees / g["slug"] / f"t{t['id']}"
        return repo, wt, branch

    def h_ticket_work(self, job: dict, p: dict) -> None:
        t = self.ticket(job["ticket_id"])
        g = self.game(t["game_id"])
        repo, wt, branch = self._wt(g, t)
        gitops.ensure_worktree(repo, wt, branch)
        self.set_ticket(t["id"], status="in_progress", branch=branch, worktree=str(wt))
        conflicts = gitops.sync_with_main(wt)
        m = self.db.one("SELECT * FROM milestones WHERE id=?", t["milestone_id"]) or {}
        pitch = self.latest_doc(g["id"], "pitch_approved") or {}
        files = gitops.git(wt, "ls-files").splitlines()
        ctx = (f"Game: {g['title']} (Godot 4.7, package {g.get('package') or '?'}, repo dir = current directory)\n"
               f"Concept summary:\n{pitch.get('content', '')[:3000]}\n\n"
               f"Milestone: {m.get('title', '')} - {m.get('goal', '')}\n"
               f"TICKET #{t['id']}: {t['title']}\n{t['description']}\n\n"
               f"Repository files ({len(files)}):\n" + "\n".join(files[:300]) + "\n")
        if conflicts:
            ctx += "\nMERGE CONFLICT with main in: " + ", ".join(conflicts) + ". Resolve the conflict markers first.\n"
        if p.get("feedback"):
            ctx += f"\nThis ticket came back to you. Fix this first:\n{p['feedback']}\n"
        task = "ticket.work"
        if (t.get("kind") or "task") == "bug":
            task = "bugfix.fix"
            ctx += (f"\nBUG severity: {t.get('severity') or '?'}\nRepro steps:\n{t.get('repro_steps') or '(see description)'}\n"
                    f"Player reports:\n{self.bug_reports_text(t)}\n"
                    f"Name the regression test tests/test_bug_t{t['id']}_<what>.gd (or tests/test_bug_t{t['id']}.gd).\n")
        data = self.call_agent(job, t["agent"], task, ctx, wt, edit=True)
        self._write_files(wt, data.get("files") or [])
        self._side_requests(g["id"], t["agent"], data, t["id"])
        gitops.commit_all(wt, f"[{t['agent']}] T#{t['id']}: {t['title']}\n\n{str(data.get('summary', ''))[:2000]}")
        if gitops.ahead_of_main(wt) == 0:
            raise AgentOutputError("agent produced no changes")
        self.log(f"T#{t['id']} work committed on {branch}: {str(data.get('summary', ''))[:200]}", g["id"], t["id"], t["agent"])
        self.set_ticket(t["id"], status="qa")
        extra = {k: data.get(k, "") for k in ("root_cause", "regression_test", "no_test_reason") if task == "bugfix.fix"}
        self.enqueue(g["id"], "qa", "qa.verify", {"summary": data.get("summary", ""), **extra}, ticket_id=t["id"])

    @staticmethod
    def _write_files(wt: Path, files: list) -> None:
        root = wt.resolve()
        for f in files:
            if not isinstance(f, dict) or not f.get("path") or f.get("content") is None:
                continue
            rel = str(f["path"]).lstrip("/").replace("res://", "")
            dest = (root / rel).resolve()
            if root not in dest.parents or ".git" in dest.relative_to(root).parts:
                raise AgentOutputError(f"refusing to write outside the project: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(str(f["content"]))

    def h_qa_verify(self, job: dict, p: dict) -> None:
        t = self.ticket(job["ticket_id"])
        g = self.game(t["game_id"])
        repo, wt, branch = self._wt(g, t)
        diff, changed = gitops.diff_vs_main(wt)
        godot = find_godot(self.db.get("godot_bin"))
        rep = run_qa(wt, changed, godot)
        if (t.get("kind") or "task") == "bug":
            self.bug_qa_checks(repo, wt, t, changed, godot, rep, p)
        ctx = (f"Game: {g['title']}\nTICKET #{t['id']} ({t['agent']}): {t['title']}\n{t['description']}\n"
               f"Agent summary: {p.get('summary', '')}\n\nAutomated QA:\n{rep.markdown()}\n\nDiff vs main:\n{diff[:60000]}\n")
        review = self.call_agent(job, "qa", "qa.review", ctx, wt, edit=False)
        # a reviewing agent must not leave edits behind: the approved commit must be exactly what was tested
        gitops.git(wt, "reset", "-q", "--hard", "HEAD")
        gitops.git(wt, "clean", "-q", "-fd")
        verdict = str(review.get("verdict", "fail")).lower()
        bugs = review.get("bugs") or []
        passed = rep.passed and verdict == "pass"
        qa_md = rep.markdown() + f"\n\n**QA agent:** {verdict.upper()} - {review.get('summary', '')}\n" + "".join(
            f"- [{b.get('severity', '?')}] {b.get('title', '')}: {b.get('details', '')}\n" for b in bugs if isinstance(b, dict))
        self.add_doc(g["id"], "qa_report", f"QA T#{t['id']} {'pass' if passed else 'fail'}", qa_md, "qa")
        loops = t["qa_loops"] or 0
        if not passed and loops < self.db.geti("qa_max_loops", 3):
            self.set_ticket(t["id"], status="changes_requested", qa_loops=loops + 1)
            self.log(f"QA failed T#{t['id']} (loop {loops + 1}); bug report sent back to {t['agent']}", g["id"], t["id"], "qa", "warn")
            self.enqueue(g["id"], t["agent"], "ticket.work", {"feedback": "QA bug report:\n" + qa_md}, ticket_id=t["id"])
            return
        sha = gitops.head(wt)
        self.set_ticket(t["id"], status="awaiting_approval")
        self.create_approval(g["id"], 3, "change", f"Merge T#{t['id']} {t['title']}" + ("" if passed else " (QA FAILED)"),
                             f"{len(changed)} files on {branch}",
                             {"ticket_id": t["id"], "branch": branch, "sha": sha, "files": changed, "diff": diff,
                              "qa_markdown": qa_md, "qa_passed": passed, "kind": t.get("kind") or "task",
                              "feedback_items": self.linked_item_ids(t["id"]),
                              "root_cause": p.get("root_cause", ""), "regression_test": p.get("regression_test", "")},
                             t["agent"], "ticket", t["id"])

    # ------------------------------------------------------------- approvals
    def approve(self, aid: int) -> dict:
        a = self._pending(aid)
        self.db.update("approvals", aid, status="approved", decided_at=now())
        self.log(f"You approved Gate {a['gate']}: {a['title']}", a["game_id"], agent="owner")
        p = loads(a["payload_json"], {}) or {}
        try:
            getattr(self, f"_on_approve_{a['kind']}")(a, p)
        except Exception as e:
            self.db.update("approvals", aid, status="pending", decided_at=None)
            self.log(f"Approval of '{a['title']}' could not be applied, still pending: {e}", a["game_id"], level="error")
            raise
        return self.db.one("SELECT * FROM approvals WHERE id=?", aid)

    def reject(self, aid: int, note: str) -> dict:
        note = (note or "").strip()
        if not note:
            raise ValueError("a rejection note is required (it is fed back to the agent)")
        a = self._pending(aid)
        self.db.update("approvals", aid, status="rejected", note=note, decided_at=now())
        self.log(f"You rejected Gate {a['gate']}: {a['title']} - {note}", a["game_id"], agent="owner", level="warn")
        p = loads(a["payload_json"], {}) or {}
        try:
            getattr(self, f"_on_reject_{a['kind']}")(a, p, note)
        except Exception as e:
            self.db.update("approvals", aid, status="pending", note=None, decided_at=None)
            self.log(f"Rejection of '{a['title']}' could not be applied, still pending: {e}", a["game_id"], level="error")
            raise
        self.db.insert("feedback", game_id=a["game_id"], agent=a["agent"], gate=a["gate"], note=note, created_at=now())
        return self.db.one("SELECT * FROM approvals WHERE id=?", aid)

    def _pending(self, aid: int) -> dict:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            if not r:
                raise KeyError(f"approval {aid} not found")
            if r["status"] != "pending":
                raise ValueError(f"approval {aid} is already {r['status']}")
            c.execute("UPDATE approvals SET status='deciding' WHERE id=?", (aid,))
            return dict(r)

    # Gate 1
    def _on_approve_concept(self, a: dict, p: dict) -> None:
        g = self.game(a["game_id"])
        doc = self.db.one("SELECT * FROM docs WHERE id=?", p.get("doc_id")) or {}
        self.add_doc(g["id"], "pitch_approved", p.get("title", g["title"]), doc.get("content", p.get("markdown", "")), "designer")
        slug, repo = self._create_repo(g, p.get("title", g["title"]), doc.get("content", ""))
        self.set_game(g["id"], slug=slug, title=p.get("title", g["title"]), repo_path=str(repo), status="planning")
        self.log(f"Repo created: games/{slug} (branch main)", g["id"], agent="producer")
        self.enqueue(g["id"], "producer", "producer.plan", {})

    def _on_reject_concept(self, a: dict, p: dict, note: str) -> None:
        self.set_game(a["game_id"], status="concept")
        self.enqueue(a["game_id"], "designer", "designer.pitch", {"feedback": note})

    # Gate 2
    def _on_approve_plan(self, a: dict, p: dict) -> None:
        gid = a["game_id"]
        base = (self.db.one("SELECT MAX(idx) AS m FROM milestones WHERE game_id=?", gid) or {}).get("m") or 0
        for i, m in enumerate(p.get("milestones") or [], 1):
            mid = self.db.insert("milestones", game_id=gid, idx=base + i, title=m["title"], goal=m.get("goal", ""), status="planned")
            for t in m["tickets"]:
                self.db.insert("tickets", game_id=gid, milestone_id=mid, agent=t["agent"], title=t["title"],
                               description=t.get("description", ""), status="todo", qa_loops=0, created_at=now(), updated_at=now())
        self.add_doc(gid, "plan", a["title"], self._plan_md(p.get("milestones") or []), "producer")
        self.set_game(gid, status="in_production")
        self.dispatch_next(gid)

    def _on_reject_plan(self, a: dict, p: dict, note: str) -> None:
        if p.get("source") == "analyst":
            return
        self.enqueue(a["game_id"], "producer", "producer.plan", {"feedback": note})

    # Gate 3
    def _on_approve_change(self, a: dict, p: dict) -> None:
        t = self.ticket(p["ticket_id"])
        g = self.game(t["game_id"])
        repo, wt, branch = self._wt(g, t)
        with self.merge_lock:
            ok, detail = gitops.merge_commit(repo, p["sha"], f"Merge T#{t['id']}: {t['title']} (approved, gate 3)")
        if not ok:
            self.db.update("approvals", a["id"], status="merge_failed", note=detail[:2000])
            self.set_ticket(t["id"], status="changes_requested")
            self.log(f"Merge of T#{t['id']} conflicted with main; sent back to {t['agent']}", g["id"], t["id"], "producer", "warn")
            self.enqueue(g["id"], t["agent"], "ticket.work",
                         {"feedback": "Your branch no longer merges cleanly into main. Merge main and resolve conflicts:\n" + detail},
                         ticket_id=t["id"])
            return
        gitops.remove_worktree(repo, wt)
        self.set_ticket(t["id"], status="done", worktree="")
        self.log(f"Merged T#{t['id']} into main ({detail[:10]})", g["id"], t["id"], "producer")
        if (t.get("kind") or "task") == "bug":
            self.on_bug_merged(t, detail)
        self.dispatch_next(g["id"])

    def _on_reject_change(self, a: dict, p: dict, note: str) -> None:
        t = self.ticket(p["ticket_id"])
        self.set_ticket(t["id"], status="changes_requested")
        self.enqueue(t["game_id"], t["agent"], "ticket.work", {"feedback": "Owner rejected the change: " + note}, ticket_id=t["id"])

    # Gate 4
    def _on_approve_spend(self, a: dict, p: dict) -> None:
        self.db.update("ledger", p["ledger_id"], status="approved", decided_at=now())
        self.log("Spend approved. The studio never pays by itself: make the purchase yourself, then mark it spent.",
                 a["game_id"], agent="producer")

    def _on_reject_spend(self, a: dict, p: dict, note: str) -> None:
        self.db.update("ledger", p["ledger_id"], status="rejected", decided_at=now())

    def mark_spent(self, ledger_id: int) -> None:
        row = self.db.one("SELECT * FROM ledger WHERE id=?", ledger_id)
        if not row or row["status"] != "approved":
            raise ValueError("only approved spends can be marked spent")
        self.db.update("ledger", ledger_id, status="spent", decided_at=now())

    # Gate 5
    def release_block_reason(self, game_id: int) -> str:
        """'' when the launch audit allows a store upload, otherwise why Gate 5 must stay closed."""
        if self.db.get("audit_required_for_release", "1") != "1":
            return ""
        au = self.latest_audit(game_id)
        if not au:
            return "no launch-readiness audit has run for this build (Games > Actions > Run launch audit)"
        g = self.game(game_id)
        cur = audit_mod.read_preset(Path(g["repo_path"])).get("version/code") if g["repo_path"] else None
        if cur and str(au["version_code"]) != str(cur):
            return f"the latest audit is for versionCode {au['version_code']} but the build is {cur}: run the audit again"
        if au["blockers"]:
            return f"the launch audit has {au['blockers']} open blocker(s) (see {au['pdf_path']})"
        return ""

    def _on_approve_release(self, a: dict, p: dict) -> None:
        why = self.release_block_reason(a["game_id"])
        if why:
            raise ValueError("Launch audit blocks the upload: " + why)
        au = self.latest_audit(a["game_id"])
        if au:
            self.set_game(a["game_id"], released_version_code=au["version_code"])
        self.set_game(a["game_id"], status="released")
        self.log("Release approved. Upload the build in Play Console yourself; this app never uploads or publishes.",
                 a["game_id"], agent="marketing")
        self.queue_fixed_replies(a["game_id"], self.game(a["game_id"]).get("version") or "")

    def _on_reject_release(self, a: dict, p: dict, note: str) -> None:
        self.set_game(a["game_id"], status="release_prep")
        self.enqueue(a["game_id"], "marketing", "marketing.release_kit", {"feedback": note, "build": p.get("build", ""),
                                                                         "qa": p.get("qa", "")})

    # Gate 6
    def _on_approve_public(self, a: dict, p: dict) -> None:
        self.add_doc(a["game_id"], "approved_post", f"Approved post ({p.get('channel')})", str(p.get("content", "")), a["agent"])
        self.log("Public post approved. Copy it from Docs and post it yourself; the studio never posts.", a["game_id"], agent="marketing")

    def _on_reject_public(self, a: dict, p: dict, note: str) -> None:
        self.enqueue(a["game_id"], "marketing", "marketing.public_redraft", {"original": p, "feedback": note})

    # ---------------------------------------------------------------- release
    def h_release_build(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        repo = Path(g["repo_path"])
        godot = find_godot(self.db.get("godot_bin"))
        files = gitops.git(repo, "ls-files").split()
        platform = g.get("platform") or "android"
        rep = run_qa(repo, files, None if platform == "roblox" else godot)
        build = "Android export disabled in Settings"
        if platform != "android":
            build = (f"SKIPPED: {platform} builds are made on your Mac by you (Xcode / Roblox Studio / web export), "
                     "see the platform track")
        elif self.db.get("qa_android_export_on_release", "1") == "1":
            ok, detail = android_export(repo, godot, repo / "build" / "android")
            build = ("SKIPPED: " if ok is None else ("OK: " if ok else "FAILED: ")) + detail
        self.add_doc(g["id"], "release_qa", "Release QA + build", rep.markdown() + "\n\n**Android build:** " + build, "qa")
        # standing rule: a launch-readiness audit runs before EVERY closed-test/production upload
        self.enqueue(g["id"], "qa", "qa.launch_audit", {"build": build, "qa": rep.markdown(), "then_release_kit": True})

    # ------------------------------------------------------- launch audit
    def latest_audit(self, game_id: int) -> dict | None:
        return self.db.one("SELECT * FROM audits WHERE game_id=? ORDER BY id DESC LIMIT 1", game_id)

    def request_audit(self, game_id: int) -> int:
        g = self.game(game_id)
        if not g["repo_path"]:
            raise ValueError("this game has no repo yet (approve its concept at Gate 1 first)")
        qa = self.latest_doc(game_id, "release_qa") or {}
        return self.enqueue(game_id, "qa", "qa.launch_audit", {"qa": qa.get("content", ""), "build": ""}, front=True)

    def h_launch_audit(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        repo = Path(g["repo_path"])
        s = self.db.settings()
        pre = audit_mod.read_preset(repo)
        version = pre.get("version/name") or g.get("version") or "0.0.0"
        try:
            code = int(pre.get("version/code") or 0)
        except ValueError:
            code = 0
        platform = g.get("platform") or "android"
        items = audit_mod.deterministic_checks(repo, g["slug"], s, p.get("qa", ""), int(g.get("released_version_code") or 0),
                                               getattr(self, "audit_fetch", None), platform)
        auto = "\n".join(f"- {i['verdict']} [{i['area']}] {i['check']}" for i in items if i["source"] == "auto")
        ctx = (f"Game: {g['title']} v{version} (versionCode {code}), package {pre.get('package/unique_name', '?')}, "
               f"platform {platform}\n"
               f"Studio: {s.get('studio_name')}, contact {s.get('contact_email')}, website {s.get('studio_website')}\n"
               f"Play account: {s.get('play_account_type')} (personal = 12 testers x 14 days closed test before production)\n\n"
               f"Automated checks already done:\n{auto}\n\nRelease QA:\n{p.get('qa', '')[:4000]}\n\nBuild: {p.get('build', '')[:800]}\n"
               f"Repository files:\n" + "\n".join(gitops.git(repo, "ls-files").splitlines()[:300]) + "\n")
        data = self.call_agent(job, "qa", "qa.launch_audit", ctx, repo, edit=False)
        gitops.git(repo, "checkout", "--", ".")  # an auditor never leaves edits behind on main
        gitops.git(repo, "clean", "-q", "-fd", "-e", "audit/")
        items = audit_mod.merge_agent_items(items, data)
        sm = audit_mod.summarize(items)
        md = audit_mod.render_markdown(g["title"], version, code, items, str(data.get("summary", ""))[:600])
        pdf = repo / "audit" / f"launch_audit_v{version}.pdf"
        audit_mod.write_pdf(md, pdf, f"{g['title']} launch audit v{version}")
        aid = self.db.insert("audits", game_id=g["id"], version=version, version_code=code, blockers=sm["blockers"],
                             todos=sm["todos"], verdict=sm["verdict"], items_json=dumps(items), markdown=md,
                             pdf_path=str(pdf), created_at=now())
        self.add_doc(g["id"], "launch_audit", f"Launch audit v{version} ({code}): {sm['verdict']}, {sm['blockers']} blocker(s)", md, "qa")
        self.set_game(g["id"], version=g.get("version") or version, version_code=code)
        lvl = "warn" if sm["blockers"] else "info"
        self.log(f"Launch audit v{version}: {sm['verdict']} ({sm['blockers']} blockers, {sm['todos']} to check). PDF: {pdf}",
                 g["id"], agent="qa", level=lvl)
        self.notify("approvals", f"Launch audit {g['title']}: {sm['verdict']}", f"{sm['blockers']} blocker(s); PDF in {pdf.parent}")
        if p.get("then_release_kit"):
            self.enqueue(g["id"], "marketing", "marketing.release_kit",
                         {"build": p.get("build", ""), "qa": p.get("qa", ""), "audit_id": aid})

    def h_release_kit(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        pitch = self.latest_doc(g["id"], "pitch_approved") or {}
        s = self.db.settings()
        ctx = (f"Game: {g['title']} (package {g.get('package') or '?'})\nStudio: {s.get('studio_name')}; contact email "
               f"{s.get('contact_email')}; website {s.get('studio_website')} (put both on the listing)\n"
               f"Concept:\n{pitch.get('content', '')[:6000]}\n\nRelease QA:\n{p.get('qa', '')[:3000]}\n")
        au = self.latest_audit(g["id"])
        if au:
            ctx += f"\nLaunch audit: {au['verdict']} with {au['blockers']} blocker(s).\n"
        if p.get("feedback"):
            ctx += f"\nOwner's rejection note on the last release kit: {p['feedback']}\n"
        data = self.call_agent(job, "marketing", "marketing.release_kit", ctx, self.scratch(g["id"]))
        ids = {}
        for key, title in (("store_listing_markdown", "Store listing (draft)"), ("screenshots_plan_markdown", "Screenshots plan"),
                           ("trailer_script_markdown", "Trailer script")):
            if data.get(key):
                ids[key] = self.add_doc(g["id"], key.replace("_markdown", ""), title, data[key], "marketing")
        if "store_listing_markdown" not in ids:
            raise AgentOutputError("release kit missing store listing")
        self._side_requests(g["id"], "marketing", {"public_actions": data.get("public_actions")})
        audit_info = {"audit_id": au["id"], "audit_verdict": au["verdict"], "audit_blockers": au["blockers"],
                      "audit_pdf": au["pdf_path"], "audit_version": au["version"], "audit_code": au["version_code"]} if au else {}
        title = f"Release {g['title']} to the store" + (f" (AUDIT: {au['blockers']} BLOCKER(S))" if au and au["blockers"] else "")
        self.create_approval(g["id"], 5, "release", title, "Store listing + build + launch audit",
                             {"build": p.get("build", ""), "qa": p.get("qa", ""), "docs": ids,
                              "store_listing": data["store_listing_markdown"], **audit_info}, "marketing")
        self.set_game(g["id"], status="release_review")

    def h_public_redraft(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        o = p.get("original") or {}
        ctx = f"Game: {g['title']}\nOriginal draft ({o.get('channel')}):\n{o.get('content')}\nOwner feedback: {p.get('feedback')}\n"
        data = self.call_agent(job, "marketing", "marketing.public_redraft", ctx, self.scratch(g["id"]))
        if not data.get("public_actions"):
            raise AgentOutputError("no redraft returned")
        self._side_requests(g["id"], "marketing", {"public_actions": data["public_actions"]})

    # ------------------------------------------------------- standup/analyst
    def board_text(self, gid: int) -> str:
        rows = self.db.all("SELECT t.id,t.agent,t.title,t.status,m.title AS ms FROM tickets t LEFT JOIN milestones m ON m.id=t.milestone_id WHERE t.game_id=? ORDER BY t.id", gid)
        pend = self.db.all("SELECT gate,title FROM approvals WHERE game_id=? AND status='pending'", gid)
        failed = self.db.all("SELECT kind,last_error FROM jobs WHERE game_id=? AND status='failed'", gid)
        return ("Tickets:\n" + "\n".join(f"- T#{r['id']} [{r['agent']}] {r['title']} :: {r['status']} ({r['ms'] or 'bug'})" for r in rows)
                + "\nWaiting on owner:\n" + "\n".join(f"- Gate {r['gate']}: {r['title']}" for r in pend)
                + "\nFailed jobs:\n" + "\n".join(f"- {r['kind']}: {(r['last_error'] or '')[:200]}" for r in failed)
                + "\n" + self.feedback_digest(gid))

    def request_standup(self, gid: int) -> int:
        return self.enqueue(gid, "producer", "producer.standup", {})

    def h_standup(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        data = self.call_agent(job, "producer", "producer.standup", f"Game: {g['title']} ({g['status']})\n{self.board_text(g['id'])}",
                               self.scratch(g["id"]))
        self.add_doc(g["id"], "standup", time.strftime("Standup %Y-%m-%d"), data.get("standup_markdown") or data.get("summary", ""), "producer")
        self.notify("standup", f"Standup: {g['title']}", (data.get("standup_markdown") or "")[:180])

    def add_inbox_file(self, gid: int, filename: str, content: bytes) -> int:
        g = self.game(gid)
        base = Path(g["repo_path"]) / "inbox" if g["repo_path"] else self.scratch(gid) / "inbox"
        base.mkdir(parents=True, exist_ok=True)
        dest = base / (re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "upload.txt")
        dest.write_bytes(content)
        return self.enqueue(gid, "analyst", "analyst.analyze", {"files": [str(dest)]})

    def h_analyze(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        chunks = []
        for f in p.get("files", []):
            raw = Path(f).read_bytes()[:40_000]
            chunks.append(f"--- {Path(f).name} ---\n" + raw.decode("utf-8", errors="replace"))
        ctx = f"Game: {g['title']} ({g['status']})\n{self.board_text(g['id'])}\n\nData files:\n" + "\n".join(chunks)
        data = self.call_agent(job, "analyst", "analyst.analyze", ctx, self.scratch(g["id"]))
        self.add_doc(g["id"], "analysis", "Analyst report", data.get("report_markdown", ""), "analyst")
        ms = self._clean_milestones([data["proposed_milestone"]] if isinstance(data.get("proposed_milestone"), dict) else [])
        if ms and g["repo_path"]:
            self.create_approval(g["id"], 2, "plan", f"Follow-up milestone: {ms[0]['title']}", self._plan_md(ms),
                                 {"milestones": ms, "source": "analyst"}, "analyst")

    # ------------------------------------------------------------- dashboard
    def state(self, game_id: int | None = None) -> dict:
        db = self.db
        s = db.settings()
        gf = "WHERE game_id=?" if game_id else ""
        args = (game_id,) if game_id else ()
        month = time.strftime("%Y-%m")
        spent = db.one("SELECT COALESCE(SUM(amount),0) AS s FROM ledger WHERE status IN ('approved','spent') AND strftime('%Y-%m', created_at, 'unixepoch')=?", month)["s"]
        return {
            "settings": {k: v for k, v in s.items()},
            "gates": GATES,
            "games": db.all("SELECT * FROM games ORDER BY id DESC"),
            "approvals": [dict(a, payload=loads(a.pop("payload_json"), {})) for a in
                          db.all(f"SELECT * FROM approvals WHERE status='pending' {'AND game_id=?' if game_id else ''} ORDER BY id", *args)],
            "decided": db.all(f"SELECT id,game_id,gate,title,status,note,decided_at FROM approvals WHERE status<>'pending' {'AND game_id=?' if game_id else ''} ORDER BY decided_at DESC LIMIT 20", *args),
            "milestones": db.all(f"SELECT * FROM milestones {gf} ORDER BY game_id, idx", *args),
            "tickets": db.all(f"SELECT * FROM tickets {gf} ORDER BY id", *args),
            "jobs": db.all(f"SELECT id,game_id,ticket_id,agent,kind,status,attempts,max_attempts,next_run_at,last_error,updated_at FROM jobs {gf} ORDER BY id DESC LIMIT 40", *args),
            "runs": db.all(f"SELECT id,job_id,game_id,agent,task,engine,model,status,error,tokens,started_at,finished_at FROM runs {gf} ORDER BY id DESC LIMIT 30", *args),
            "events": db.all(f"SELECT * FROM events {gf} ORDER BY id DESC LIMIT 60", *args),
            "docs": db.all(f"SELECT id,game_id,kind,title,agent,created_at FROM docs {gf} ORDER BY id DESC LIMIT 60", *args),
            "ledger": db.all(f"SELECT * FROM ledger {gf} ORDER BY id DESC", *args),
            "budget": {"monthly": float(s.get("monthly_budget") or 0), "committed_this_month": spent, "currency": s.get("currency", "EUR")},
            "queue": {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")},
            "godot": find_godot(s.get("godot_bin", "")),
            "roles": ROLES,
            "agents": self.agents_brief(),
            "feedback_counts": {r["status"]: r["n"] for r in db.all(f"SELECT status, COUNT(*) AS n FROM feedback_items {gf} GROUP BY status", *args)},
            "now": now(),
        }
