"""Agent management + live status (mixed into `Studio`): per-agent enable/pause/engine/model/effort,
run-now, prompt editing with reset-to-default, rejection-feedback memory, engine backoff state, caps."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .config import API_KEY_ENV, ENGINES, SECRET_ENV
from .db import dumps, loads, now
from .godot import find_godot, run_qa
from .notify import in_range, parse_range
from .prompts import ROLES, RUN_NOW

PROMPT_DEFAULTS = Path(__file__).parent / "prompt_defaults"
EFFORTS = ["", "low", "medium", "high"]
AGENT_LABEL = {"producer": "Producer", "designer": "Game Designer", "engineer": "Engineer", "artist": "Artist", "qa": "QA",
               "marketing": "Marketing", "analyst": "Analyst", "support": "Customer Support", "bugfixer": "Bug Fixer"}
AGENT_BLURB = {
    "producer": "Milestones, tickets, routing, daily standup",
    "designer": "Concept pitches, GDD, levels, economy",
    "engineer": "Godot 4.7 GDScript on its own branch, with tests; researches proven open-source designs first",
    "artist": "Placeholder/procedural art, UI, icons, prompt sheets",
    "qa": "Headless Godot tests, smoke run, diff review, Android export",
    "marketing": "Store listing, screenshots plan, trailer, social drafts",
    "analyst": "Reads your exports and proposes next steps",
    "support": "Player feedback inbox: dedup, classify, group, draft replies (Gate 6)",
    "bugfixer": "Bug tickets from player reports, test-first fixes to Gate 3",
}


class ManagementMixin:
    # ------------------------------------------------------------------ agent config
    def seed_agents(self) -> None:
        with self.db.tx() as c:
            for r in ROLES:
                c.execute("INSERT OR IGNORE INTO agents(name, updated_at) VALUES(?,?)", (r, now()))

    def agent_cfg(self, name: str) -> dict:
        return self.db.one("SELECT * FROM agents WHERE name=?", name) or {"name": name, "enabled": 1, "paused": 0,
                                                                           "engine": "", "model": "", "effort": ""}

    def set_agent(self, name: str, **fields) -> dict:
        if name not in ROLES:
            raise KeyError(f"agent {name} not found")
        cols = {}
        for k in ("enabled", "paused"):
            if k in fields and fields[k] is not None:
                cols[k] = 1 if str(fields[k]).lower() in ("1", "true", "yes", "on") else 0
        if fields.get("engine") is not None:
            if fields["engine"] not in [""] + ENGINES:
                raise ValueError(f"engine must be one of {ENGINES} or empty (= default)")
            cols["engine"] = fields["engine"]
        if fields.get("model") is not None:
            m = str(fields["model"]).strip()
            if len(m) > 200 or not re.fullmatch(r"[\w.:/@+-]*", m):
                raise ValueError("model name has unexpected characters")
            cols["model"] = m
        if fields.get("effort") is not None:
            if fields["effort"] not in EFFORTS:
                raise ValueError("effort must be low, medium, high or empty")
            cols["effort"] = fields["effort"]
        if cols:
            with self.db.tx() as c:
                c.execute(f"UPDATE agents SET {','.join(k + '=?' for k in cols)}, updated_at=? WHERE name=?", (*cols.values(), now(), name))
            self.log(f"Agent {name} settings changed: " + ", ".join(f"{k}={v}" for k, v in cols.items()), agent="owner")
        return self.agent_cfg(name)

    def blocked_agents(self) -> list[str]:
        return [r["name"] for r in self.db.all("SELECT name FROM agents WHERE enabled=0 OR paused=1")]

    def agents_brief(self) -> list[dict]:
        return self.db.all("SELECT * FROM agents")

    # ------------------------------------------------------------------ prompts
    def _prompt_name(self, name: str) -> str:
        if name not in ["_common"] + ROLES:
            raise KeyError(f"prompt {name} not found")
        return name

    def get_prompt(self, name: str) -> dict:
        name = self._prompt_name(name)
        cur, dflt = self.paths.prompts / f"{name}.md", PROMPT_DEFAULTS / f"{name}.md"
        content = cur.read_text() if cur.exists() else ""
        default = dflt.read_text() if dflt.exists() else ""
        return {"name": name, "content": content, "default": default, "customized": content != default,
                "path": str(cur)}

    def save_prompt(self, name: str, content: str) -> dict:
        name = self._prompt_name(name)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("prompt is empty")
        if len(content) > 200_000:
            raise ValueError("prompt too long (200 KB max)")
        self.paths.prompts.mkdir(parents=True, exist_ok=True)
        (self.paths.prompts / f"{name}.md").write_text(content)
        self.log(f"Prompt {name}.md edited in the dashboard", agent="owner")
        return self.get_prompt(name)

    def reset_prompt(self, name: str) -> dict:
        name = self._prompt_name(name)
        src = PROMPT_DEFAULTS / f"{name}.md"
        if not src.exists():
            raise KeyError(f"no default for {name}")
        self.paths.prompts.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, self.paths.prompts / f"{name}.md")
        self.log(f"Prompt {name}.md reset to default", agent="owner")
        return self.get_prompt(name)

    def agent_feedback(self, name: str) -> list[dict]:
        if name not in ROLES:
            raise KeyError(f"agent {name} not found")
        return self.db.all("SELECT f.*, g.title AS game_title FROM feedback f LEFT JOIN games g ON g.id=f.game_id "
                           "WHERE f.agent=? ORDER BY f.id DESC LIMIT 200", name)

    def delete_agent_feedback(self, fid: int) -> None:
        if not self.db.one("SELECT id FROM feedback WHERE id=?", fid):
            raise KeyError(f"feedback note {fid} not found")
        with self.db.tx() as c:
            c.execute("DELETE FROM feedback WHERE id=?", (fid,))

    # ------------------------------------------------------------------ run now
    def run_now(self, agent: str, game_id: int | None) -> int:
        if agent not in ROLES:
            raise KeyError(f"agent {agent} not found")
        cfg = self.agent_cfg(agent)
        if not cfg["enabled"]:
            raise ValueError(f"{agent} is disabled; enable it first")
        g = self.game(game_id) if game_id else None
        if agent == "support":
            return self.enqueue(game_id, "support", "support.ingest", {"reason": "run now"}, front=True)
        if not g:
            raise ValueError("pick a game")
        if agent == "producer":
            return self.enqueue(g["id"], "producer", "producer.standup", {}, front=True)
        if agent == "designer":
            if g["status"] not in ("concept",):
                raise ValueError("the Designer pitches only for games at concept stage (reject the pitch to get a new one)")
            return self.enqueue(g["id"], "designer", "designer.pitch", {}, front=True)
        if not g["repo_path"]:
            raise ValueError("this game has no repo yet (approve its concept at Gate 1 first)")
        if agent in ("engineer", "artist", "bugfixer"):
            busy = {r["ticket_id"] for r in self.db.all("SELECT ticket_id FROM jobs WHERE status IN ('queued','running') AND ticket_id IS NOT NULL")}
            kind = "AND kind='bug'" if agent == "bugfixer" else ""
            for t in self.db.all(f"SELECT * FROM tickets WHERE game_id=? AND agent=? {kind} AND status IN ('todo','queued','needs_attention','changes_requested') ORDER BY id",
                                 g["id"], agent):
                if t["id"] not in busy:
                    self.set_ticket(t["id"], status="queued")
                    return self.enqueue(g["id"], agent, "ticket.work", {}, ticket_id=t["id"], front=True)
            if agent == "bugfixer":
                for grp in self.db.all("SELECT id FROM feedback_groups WHERE game_id=? AND category IN ('bug','crash') AND bug_ticket_id IS NULL ORDER BY count DESC", g["id"]):
                    jid = self.maybe_bug_intake(grp["id"], force=True)
                    if jid:
                        return jid
            raise ValueError(f"no open {agent} work for {g['title']}")
        if agent == "qa":
            return self.enqueue(g["id"], "qa", "qa.health", {}, front=True)
        if agent == "marketing":
            qa = self.latest_doc(g["id"], "release_qa") or {}
            return self.enqueue(g["id"], "marketing", "marketing.release_kit", {"qa": qa.get("content", ""), "build": ""}, front=True)
        if agent == "analyst":
            inbox = Path(g["repo_path"]) / "inbox"
            files = sorted(str(f) for f in inbox.glob("*") if f.is_file()) if inbox.exists() else []
            if not files:
                raise ValueError("the Analyst inbox for this game is empty: upload an export first")
            return self.enqueue(g["id"], "analyst", "analyst.analyze", {"files": files[-10:]}, front=True)
        raise ValueError(f"run-now is not available for {agent}")

    def h_qa_health(self, job: dict, p: dict) -> None:
        g = self.game(job["game_id"])
        repo = Path(g["repo_path"])
        from . import gitops
        rep = run_qa(repo, gitops.git(repo, "ls-files").split(), find_godot(self.db.get("godot_bin")))
        self.add_doc(g["id"], "qa_report", f"QA health check on main: {'pass' if rep.passed else 'FAIL'}", rep.markdown(), "qa")
        self.log(f"QA health check on main: {'passed' if rep.passed else 'FAILED'}", g["id"], agent="qa",
                 level="info" if rep.passed else "warn")

    # ------------------------------------------------------------------ limits & backoff
    def spend_flags(self, amount: float) -> list[str]:
        flags = []
        cap = float(self.db.get("spend_cap_per_request") or 0)
        if cap and amount > cap:
            flags.append(f"OVER PER-REQUEST CAP {cap:g}")
        budget = float(self.db.get("monthly_budget") or 0)
        if budget:
            month = time.strftime("%Y-%m")
            spent = self.db.one("SELECT COALESCE(SUM(amount),0) s FROM ledger WHERE status IN ('approved','spent') AND strftime('%Y-%m', created_at, 'unixepoch')=?", month)["s"]
            if spent + amount > budget:
                flags.append("OVER MONTHLY BUDGET")
        return flags

    def set_engine_backoff(self, engine: str, seconds: float, reason: str) -> None:
        st = loads(self.db.get("engine_backoff"), {}) or {}
        st[engine or "?"] = {"until": now() + seconds, "reason": reason[:300], "at": now()}
        self.db.set("engine_backoff", dumps(st))

    def clear_engine_backoff(self, engine: str) -> None:
        st = loads(self.db.get("engine_backoff"), {}) or {}
        if engine in st:
            st.pop(engine)
            self.db.set("engine_backoff", dumps(st))

    def _day_start(self) -> float:
        t = time.localtime()
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))

    def usage_today(self) -> dict:
        r = self.db.one("SELECT COUNT(*) n, COALESCE(SUM(tokens),0) t FROM runs WHERE started_at>=?", self._day_start())
        return {"runs": r["n"], "tokens": r["t"]}

    def hold_reason(self) -> str:
        """Why the worker should not start a new run right now ('' = go)."""
        s = self.db.settings()
        wh = s.get("work_hours", "")
        if parse_range(wh) and not in_range(wh):
            return f"outside work hours ({wh})"
        u = self.usage_today()
        rc, tc = int(float(s.get("daily_run_cap") or 0)), int(float(s.get("daily_token_cap") or 0))
        if rc and u["runs"] >= rc:
            return f"daily run cap reached ({u['runs']}/{rc})"
        if tc and u["tokens"] >= tc:
            return f"daily token cap reached ({u['tokens']}/{tc})"
        return ""

    # ------------------------------------------------------------------ status
    def agent_status(self, name: str, global_paused: bool, t: float) -> dict:
        cfg = self.agent_cfg(name)
        running = self.db.all("SELECT j.id, j.kind, j.game_id, j.ticket_id, j.started_at, g.title AS game_title FROM jobs j "
                              "LEFT JOIN games g ON g.id=j.game_id WHERE j.agent=? AND j.status='running' ORDER BY j.id", name)
        queued = self.db.all("SELECT id, kind, game_id, ticket_id, next_run_at, attempts, last_error FROM jobs WHERE agent=? AND status='queued' ORDER BY next_run_at, id", name)
        last_job = self.db.one("SELECT id, kind, status, last_error, finished_at, updated_at FROM jobs WHERE agent=? AND status IN ('done','failed') ORDER BY updated_at DESC, id DESC LIMIT 1", name)
        runs = self.db.all("SELECT id, task, engine, model, status, error, summary, tokens, started_at, finished_at, game_id FROM runs WHERE agent=? ORDER BY id DESC LIMIT 6", name)
        backoff = [q for q in queued if (q["attempts"] or 0) > 0 and (q["next_run_at"] or 0) > t]
        if not cfg["enabled"]:
            state = "disabled"
        elif running:
            state = "running"
        elif cfg["paused"] or global_paused:
            state = "paused"
        elif last_job and last_job["status"] == "failed":
            state = "error"
        elif queued:
            state = "queued"
        else:
            state = "idle"
        cur = running[0] if running else None
        last = runs[0] if runs else None
        return {
            "name": name, "label": AGENT_LABEL.get(name, name), "blurb": AGENT_BLURB.get(name, ""), "state": state,
            "enabled": bool(cfg["enabled"]), "paused": bool(cfg["paused"]), "engine": cfg["engine"], "model": cfg["model"],
            "effort": cfg["effort"], "run_now": RUN_NOW.get(name, ""),
            "current": cur and {"job_id": cur["id"], "kind": cur["kind"], "game": cur["game_title"], "game_id": cur["game_id"],
                                "ticket_id": cur["ticket_id"], "since": cur["started_at"]},
            "queue_length": len(queued), "backoff_jobs": len(backoff),
            "next_due": min((q["next_run_at"] for q in queued), default=None),
            "last_run_at": (last or {}).get("finished_at") or (last or {}).get("started_at"),
            "last_result": last and {"run_id": last["id"], "task": last["task"], "status": last["status"],
                                     "summary": (last["summary"] or last["error"] or "")[:300]},
            "last_error": (last_job or {}).get("last_error") if state == "error" else None,
            "recent_runs": runs,
            "feedback_notes": self.db.one("SELECT COUNT(*) n FROM feedback WHERE agent=?", name)["n"],
        }

    def status(self) -> dict:
        import os
        s = self.db.settings()
        t = now()
        gp = s.get("paused") == "1"
        eb = loads(s.get("engine_backoff"), {}) or {}
        engines = {k: {**v, "remaining": max(0, int(v.get("until", 0) - t))} for k, v in eb.items() if v.get("until", 0) > t}
        appr = self.db.all("SELECT gate, COUNT(*) n FROM approvals WHERE status='pending' GROUP BY gate")
        return {
            "now": t,
            "paused": gp, "pause_reason": s.get("pause_reason", ""),
            "hold_reason": self.hold_reason(),
            "engine": s.get("engine"), "chore_engine": s.get("chore_engine", ""),
            "setup_complete": s.get("setup_complete") == "1", "studio_name": s.get("studio_name", ""),
            "concurrency": int(float(s.get("concurrency") or 1)),
            "queue": {r["status"]: r["n"] for r in self.db.all("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")},
            "engine_backoff": engines,
            "approvals_waiting": {str(r["gate"]): r["n"] for r in appr},
            "approvals_total": sum(r["n"] for r in appr),
            "feedback_new": self.db.one("SELECT COUNT(*) n FROM feedback_items WHERE status IN ('new','triaged','reply_drafted')")["n"],
            "usage_today": self.usage_today(),
            "caps": {"daily_run_cap": s.get("daily_run_cap"), "daily_token_cap": s.get("daily_token_cap")},
            "work_hours": s.get("work_hours", ""), "quiet_hours": s.get("quiet_hours", ""),
            "standup_time": s.get("standup_time", ""),
            "godot": find_godot(s.get("godot_bin", "")),
            "secrets": {k: ("set" if (self.secrets.get(k) if k in API_KEY_ENV else os.environ.get(k)) else "not set") for k in SECRET_ENV},
            "agents": [self.agent_status(r, gp, t) for r in ROLES],
            "games": self.db.all("SELECT id, title, slug, status, version FROM games ORDER BY id DESC"),
        }
