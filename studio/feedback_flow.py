"""Customer Support + Bug Fixer agents (mixed into `Studio`).

Support:  sources -> support.ingest (deterministic parse/dedup/link) -> support.triage (LLM classify +
          draft replies, validated) -> deterministic grouping -> reply drafts as Gate 6 approvals.
Bug Fixer: bug/crash groups (or owner-flagged items) -> bugfix.intake (ticket with repro steps) ->
          ticket.work with the bugfix.fix contract on its own branch -> qa.verify -> Gate 3 (diff + QA).
          After the merge the items are marked fixed; after Gate 5 (release) Support drafts
          "fixed in vX" follow-ups, again as Gate 6 drafts. The studio never posts or sends anything.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from . import gitops
from . import support as sp
from .db import dumps, loads, now

CHANNEL_LABEL = {"play": "Google Play review reply", "email": "Email reply", "ingame": "In-game / support reply"}


class SupportMixin:
    # ------------------------------------------------------------------ sources
    def feedback_dir(self) -> Path:
        v = (self.db.get("feedback_inbox_dir") or "feedback").strip()
        p = Path(v).expanduser()
        p = p if p.is_absolute() else self.paths.home / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve_game(self, hint: str, text: str = "") -> int | None:
        h = (hint or "").strip().lower()
        games = self.db.all("SELECT id, slug, title, package FROM games")
        for g in games:
            if h and h in {g["slug"].lower(), (g["package"] or "").lower(), g["title"].lower()}:
                return g["id"]
        gmap = {str(k).lower(): str(v) for k, v in (loads(self.db.get("feedback_game_map"), {}) or {}).items()}
        by_slug = {g["slug"]: g["id"] for g in games}
        if h in gmap and gmap[h] in by_slug:
            return by_slug[gmap[h]]
        hay = f"{hint} {text[:2000]}".lower()
        for k, slug in gmap.items():
            if k and k in hay and slug in by_slug:
                return by_slug[slug]
        for g in games:  # an email subject such as "Ferry Out keeps crashing"
            if len(g["title"]) >= 4 and g["title"].lower() != "untitled concept" and g["title"].lower() in hint.lower():
                return g["id"]
        return None

    def ingest_items(self, raws: list[sp.RawItem]) -> dict:
        new, dup, updated = [], 0, []
        for r in raws:
            text = (r.text or "").strip()
            if not text:
                continue
            fp = sp.fingerprint(text, r.author, r.game_hint)
            if r.external_id:
                ex = self.db.one("SELECT * FROM feedback_items WHERE source=? AND external_id=?", r.source, r.external_id)
                if ex:
                    if ex["fingerprint"] != fp or (r.rating is not None and ex["rating"] != r.rating):
                        # the player edited the review: re-triage it
                        self.db.update("feedback_items", ex["id"], text=text, title=r.title, rating=r.rating, fingerprint=fp,
                                       app_version=r.app_version or ex["app_version"], category=None, status="new",
                                       submitted_at=r.submitted_at, updated_at=now())
                        updated.append(ex["id"])
                    else:
                        dup += 1
                    continue
            ex = self.db.one("SELECT id, duplicates FROM feedback_items WHERE fingerprint=?", fp)
            if ex:
                self.db.update("feedback_items", ex["id"], duplicates=(ex["duplicates"] or 0) + 1, updated_at=now())
                dup += 1
                continue
            gid = self.resolve_game(r.game_hint, f"{r.title} {text}")
            raw = dict(r.raw or {}, category_hint=r.category_hint, game_hint=r.game_hint)
            iid = self.db.insert("feedback_items", game_id=gid, source=r.source, source_ref=r.source_ref,
                                 external_id=r.external_id or None, fingerprint=fp, author=r.author, rating=r.rating,
                                 language=r.language, device=r.device, app_version=r.app_version, title=r.title,
                                 text=text[:20000], submitted_at=r.submitted_at, ingested_at=now(),
                                 status="replied" if r.already_replied else "new", reply_channel=r.reply_channel,
                                 raw_json=dumps(raw)[:20000], updated_at=now())
            new.append(iid)
        return {"new": new, "duplicates": dup, "updated": updated}

    def ingest_sources(self, include_imap: bool = True) -> dict:
        root = self.feedback_dir()
        stats = {"files": 0, "new": 0, "duplicates": 0, "updated": 0, "imap": 0, "errors": []}
        ids: list[int] = []
        for f in sp.scan_folder(root):
            key = str(f.resolve())
            sha = sp.sha_file(f)
            seen = self.db.one("SELECT sha FROM ingested_files WHERE path=?", key)
            if seen and seen["sha"] == sha:
                continue
            try:
                res = self.ingest_items(sp.parse_file(f, root))
            except Exception as e:  # noqa: BLE001 - one bad file must not block the rest
                stats["errors"].append(f"{f.name}: {e}")
                res = {"new": [], "duplicates": 0, "updated": []}
            with self.db.tx() as c:
                c.execute("INSERT INTO ingested_files(path,sha,items,ingested_at) VALUES(?,?,?,?) "
                          "ON CONFLICT(path) DO UPDATE SET sha=excluded.sha, items=excluded.items, ingested_at=excluded.ingested_at",
                          (key, sha, len(res["new"]), now()))
            stats["files"] += 1
            ids += res["new"] + res["updated"]
            stats["duplicates"] += res["duplicates"]
            stats["updated"] += len(res["updated"])
        if include_imap and self.db.get("feedback_imap_enabled") == "1":
            try:
                raws = sp.fetch_imap(self.db.get("feedback_imap_folder") or "INBOX", self.db.get("feedback_imap_search") or "UNSEEN",
                                     self.db.geti("feedback_imap_max", 50), factory=getattr(self, "imap_factory", None))
                res = self.ingest_items(raws)
                stats["imap"] = len(res["new"])
                ids += res["new"] + res["updated"]
                stats["duplicates"] += res["duplicates"]
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"IMAP: {e}")
        stats["new"] = len(ids) - stats["updated"]
        self.db.set("last_feedback_scan", str(int(now())))
        return {**stats, "ids": ids}

    def has_new_feedback_files(self) -> bool:
        root = self.feedback_dir()
        for f in sp.scan_folder(root):
            seen = self.db.one("SELECT sha FROM ingested_files WHERE path=?", str(f.resolve()))
            if not seen or seen["sha"] != sp.sha_file(f):
                return True
        return False

    def add_feedback_file(self, filename: str, data: bytes, game_slug: str = "") -> int:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "feedback.txt").name) or "feedback.txt"
        if Path(name).suffix.lower() not in sp.FEEDBACK_EXT:
            raise ValueError("feedback files must be .csv, .json or .txt")
        base = self.feedback_dir()
        if game_slug:
            if not self.db.one("SELECT id FROM games WHERE slug=?", game_slug):
                raise KeyError(f"game {game_slug} not found")
            base = base / game_slug
            base.mkdir(parents=True, exist_ok=True)
        dest = base / name
        if dest.exists():
            dest = base / f"{dest.stem}-{int(now() * 1000)}{dest.suffix}"
        dest.write_bytes(data)
        return self.enqueue(None, "support", "support.ingest", {"reason": f"upload {dest.name}"}, front=True)

    def add_ingame_feedback(self, payload: Any) -> int:
        if not isinstance(payload, (dict, list)):
            raise ValueError("send a JSON object or list")
        data = json.dumps(payload, ensure_ascii=False).encode()
        if len(data) > 2_000_000:
            raise ValueError("payload too large")
        return self.add_feedback_file(f"ingame-{int(now() * 1000)}.json", data)

    # ------------------------------------------------------------------ jobs
    def h_support_ingest(self, job: dict, p: dict) -> None:
        stats = self.ingest_sources(include_imap=True)
        for e in stats["errors"]:
            self.log(f"Feedback source problem: {e}", agent="support", level="error")
        ids = set(stats["ids"])
        # also pick up anything never triaged (e.g. after a crash or a failed triage)
        ids |= {r["id"] for r in self.db.all("SELECT id FROM feedback_items WHERE category IS NULL")}
        by_game: dict[Any, list[int]] = {}
        for r in self.db.all(f"SELECT id, game_id FROM feedback_items WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", *ids):
            by_game.setdefault(r["game_id"], []).append(r["id"])
        queued_ids = set()
        for j in self.db.all("SELECT payload_json FROM jobs WHERE kind='support.triage' AND status IN ('queued','running')"):
            queued_ids |= set((loads(j["payload_json"], {}) or {}).get("item_ids") or [])
        n = 0
        for gid, items in by_game.items():
            items = sorted(set(items) - queued_ids)
            for batch in sp.iter_batches(items, self.db.geti("support_batch_size", 20)):
                self.enqueue(gid, "support", "support.triage", {"item_ids": batch})
                n += 1
        self.log(f"Feedback scan: {stats['files']} file(s), {stats['new']} new, {stats['updated']} edited, "
                 f"{stats['duplicates']} duplicate(s), {stats['imap']} from mail; {n} triage batch(es) queued", agent="support")

    def _items(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        return self.db.all(f"SELECT * FROM feedback_items WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", *ids)

    def _items_block(self, rows: list[dict]) -> str:
        titles = {g["id"]: g["title"] for g in self.db.all("SELECT id, title FROM games")}
        data = [{"id": r["id"], "source": r["source"], "rating": r["rating"], "title": r["title"] or "",
                 "text": (r["text"] or "")[:2000], "version": r["app_version"] or "", "device": r["device"] or "",
                 "language": r["language"] or "", "game": titles.get(r["game_id"], ""),
                 "type_hint": (loads(r["raw_json"], {}) or {}).get("category_hint", "")} for r in rows]
        return "<<<FEEDBACK_ITEMS\n" + json.dumps(data, ensure_ascii=False) + "\nFEEDBACK_ITEMS>>>"

    def h_support_triage(self, job: dict, p: dict) -> None:
        rows = [r for r in self._items(p.get("item_ids") or []) if r["category"] is None or p.get("force")]
        if not rows:
            return
        gid = job.get("game_id")
        groups = self.db.all("SELECT id, category, title, count FROM feedback_groups WHERE game_id IS ? ORDER BY count DESC LIMIT 30", gid)
        ctx = (f"Game: {self.game(gid)['title'] if gid else '(not linked to a game yet)'}\n"
               "Known issue groups (reuse a group_label when it is the same issue):\n"
               + "\n".join(f"- {g['title']} [{g['category']}, {g['count']} reports]" for g in groups)
               + "\n\nFeedback items:\n" + self._items_block(rows) + "\n")
        data = self.call_agent(job, "support", "support.triage", ctx, self.scratch(gid or 0))
        res = {}
        for it in data.get("items") or []:
            try:
                res[int(it.get("id"))] = it
            except (TypeError, ValueError):
                continue
        touched, critical = set(), []
        for r in rows:
            out = res.get(r["id"]) or {}
            hint = (loads(r["raw_json"], {}) or {}).get("category_hint", "")
            rule = sp.rule_classify(f"{r['title'] or ''} {r['text']}", r["rating"], hint)
            cat = str(out.get("category", "")).lower().strip().replace(" ", "_")
            cat = cat if cat in sp.CATEGORIES else rule["category"]
            sent = str(out.get("sentiment", "")).lower()
            sent = sent if sent in sp.SENTIMENTS else rule["sentiment"]
            sev = str(out.get("severity", "")).lower().replace("medium", "med")
            sev = sev if sev in sp.SEVERITIES else rule["severity"]
            summary = str(out.get("summary") or r["text"][:120]).strip()[:300]
            label = str(out.get("group_label") or summary)[:80]
            self.db.update("feedback_items", r["id"], category=cat, sentiment=sent, severity=sev, summary=summary,
                           status="triaged" if r["status"] == "new" else r["status"], updated_at=now())
            grp = self.assign_group(r["id"], label)
            touched.add(grp)
            if sev == "critical":
                critical.append(summary)
            needs = out.get("needs_reply", True) is not False and cat != "abuse"
            if r["status"] in ("replied", "closed", "ignored") or not needs:
                continue
            reply = str(out.get("reply_draft") or "").strip() or sp.default_reply(r, {"category": cat}, self._gtitle(r["game_id"]))
            if reply:
                self.db.update("feedback_items", r["id"], reply_draft=reply[:4000], status="reply_drafted", updated_at=now())
                if self.db.get("support_reply_to_gate6", "1") == "1":
                    self.request_reply_approval(r["id"])
        for g in touched:
            self.maybe_bug_intake(g)
        if critical:
            self.notify("feedback", f"{len(critical)} critical player report(s)", critical[0])
        self.log(f"Triaged {len(rows)} feedback item(s) into {len(touched)} group(s)", gid, agent="support")

    def _gtitle(self, gid: int | None) -> str:
        if not gid:
            return "the game"
        g = self.db.one("SELECT title FROM games WHERE id=?", gid)
        return g["title"] if g else "the game"

    # ------------------------------------------------------------------ grouping (deterministic)
    def assign_group(self, item_id: int, label: str = "") -> int:
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        tk = sp.tokens(f"{it['title'] or ''} {it['text']}") | sp.tokens(label)
        fam = sp.BUGGY if it["category"] in sp.BUGGY else {it["category"]}
        best, score = None, 0.0
        for g in self.db.all(f"SELECT * FROM feedback_groups WHERE game_id IS ? AND category IN ({','.join('?' * len(fam))})",
                             it["game_id"], *fam):
            s = sp.jaccard(tk, set(loads(g["tokens"], []) or []))
            if label and sp.normalize(label) == sp.normalize(g["title"] or ""):
                s = max(s, 1.0)
            if s > score:
                best, score = g, s
        if it["group_id"]:
            old = self.db.one("SELECT * FROM feedback_groups WHERE id=?", it["group_id"])
            if old and best and old["id"] == best["id"]:
                return old["id"]
            if old:
                self.db.update("feedback_groups", old["id"], count=max(0, (old["count"] or 1) - 1), updated_at=now())
        if best and score >= 0.34:
            sev = max([best["severity"] or "low", it["severity"] or "low"], key=lambda x: sp.SEV_RANK.get(x, 0))
            cat = "crash" if "crash" in (best["category"], it["category"]) else best["category"]
            self.db.update("feedback_groups", best["id"], count=(best["count"] or 0) + 1, severity=sev, category=cat, updated_at=now())
            gid = best["id"]
        else:
            gid = self.db.insert("feedback_groups", game_id=it["game_id"], category=it["category"], title=(label or it["summary"] or "")[:120],
                                 tokens=dumps(sorted(tk)[:60]), severity=it["severity"], count=1, created_at=now(), updated_at=now())
        grp = self.db.one("SELECT bug_ticket_id FROM feedback_groups WHERE id=?", gid)
        self.db.update("feedback_items", item_id, group_id=gid,
                       bug_ticket_id=grp["bug_ticket_id"] if (grp["bug_ticket_id"] or 0) > 0 else it["bug_ticket_id"])
        return gid

    # ------------------------------------------------------------------ replies (Gate 6, drafts only)
    def request_reply_approval(self, item_id: int) -> int:
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        if not it:
            raise KeyError(f"feedback item {item_id} not found")
        if not (it["reply_draft"] or "").strip():
            raise ValueError("this item has no reply draft")
        chan = CHANNEL_LABEL.get(it["reply_channel"] or "", "Reply (post it where the player wrote)")
        if it["reply_channel"] == "email" and it["author"]:
            chan = f"Email reply to {it['author']}"
        stars = f"{it['rating']}-star " if it["rating"] else ""
        followup = bool(it["fixed_in_version"])
        title = (f"Follow-up reply (fixed in {it['fixed_in_version']})" if followup else f"Reply to {stars}{it['source']} feedback") + \
            f": {(it['summary'] or it['text'])[:70]}"
        raw = loads(it["raw_json"], {}) or {}
        payload = {"item_id": it["id"], "channel": chan, "content": it["reply_draft"], "player_text": it["text"][:3000],
                   "rating": it["rating"], "category": it["category"], "review_link": raw.get("review_link", ""), "followup": followup}
        if it["reply_approval_id"]:
            a = self.db.one("SELECT status FROM approvals WHERE id=?", it["reply_approval_id"])
            if a and a["status"] == "pending":
                # one pending reply per player: the newest draft replaces the one still waiting
                self.db.update("approvals", it["reply_approval_id"], title=title, summary=it["reply_draft"][:300], payload_json=dumps(payload))
                return it["reply_approval_id"]
        aid = self.create_approval(it["game_id"], 6, "reply", title, it["reply_draft"][:300], payload, "support", "feedback", it["id"])
        self.db.update("feedback_items", it["id"], reply_approval_id=aid, status="awaiting_approval", updated_at=now())
        return aid

    def edit_reply_draft(self, item_id: int, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("reply text is empty")
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        if not it:
            raise KeyError(f"feedback item {item_id} not found")
        self.db.update("feedback_items", item_id, reply_draft=text[:4000], updated_at=now(),
                       status=it["status"] if it["status"] == "awaiting_approval" else "reply_drafted")
        if it["reply_approval_id"]:
            a = self.db.one("SELECT * FROM approvals WHERE id=?", it["reply_approval_id"])
            if a and a["status"] == "pending":
                pl = loads(a["payload_json"], {}) or {}
                pl["content"] = text
                self.db.update("approvals", a["id"], payload_json=dumps(pl), summary=text[:300])
        return self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)

    def _on_approve_reply(self, a: dict, p: dict) -> None:
        self.db.update("feedback_items", p["item_id"], status="reply_approved", reply_draft=p.get("content"), updated_at=now())
        self.log("Reply approved. Copy it from the Feedback inbox and post/send it yourself; the studio never posts or emails.",
                 a["game_id"], agent="support")

    def _on_reject_reply(self, a: dict, p: dict, note: str) -> None:
        self.db.update("feedback_items", p["item_id"], status="reply_drafted", updated_at=now())
        self.enqueue(a["game_id"], "support", "support.redraft_reply", {"item_id": p["item_id"], "previous": p.get("content", ""),
                                                                        "feedback": note})

    def h_support_redraft(self, job: dict, p: dict) -> None:
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", p["item_id"])
        ctx = (f"Game: {self._gtitle(it['game_id'])}\nPlayer wrote ({it['rating'] or '-'} stars, {it['source']}):\n{it['text'][:3000]}\n\n"
               f"Your previous draft:\n{p.get('previous', '')}\n\nOwner's note: {p.get('feedback', '')}\n")
        data = self.call_agent(job, "support", "support.redraft_reply", ctx, self.scratch(it["game_id"] or 0))
        reply = str(data.get("reply_draft") or "").strip()
        if not reply:
            from .workflow import AgentOutputError
            raise AgentOutputError("no reply_draft returned")
        self.db.update("feedback_items", it["id"], reply_draft=reply[:4000], reply_approval_id=None, status="reply_drafted", updated_at=now())
        self.request_reply_approval(it["id"])

    def set_feedback_status(self, item_id: int, status: str) -> dict:
        if status not in sp.STATUSES:
            raise ValueError(f"status must be one of {sp.STATUSES}")
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        if not it:
            raise KeyError(f"feedback item {item_id} not found")
        if status == "replied" and it["status"] not in ("reply_approved", "replied") and it["reply_draft"]:
            raise ValueError("approve the reply at Gate 6 first, then mark it replied after you posted it")
        self.db.update("feedback_items", item_id, status=status, updated_at=now())
        return self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)

    def set_feedback_game(self, item_id: int, game_id: int | None) -> dict:
        if game_id:
            self.game(game_id)
        self.db.update("feedback_items", item_id, game_id=game_id, updated_at=now())
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        if not it:
            raise KeyError(f"feedback item {item_id} not found")
        if it["category"]:
            self.maybe_bug_intake(self.assign_group(item_id, it["summary"] or ""))
        return self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)

    def flag_bug(self, item_id: int) -> int | None:
        """Owner says 'this is a bug': send it to the Bug Fixer regardless of the severity threshold."""
        it = self.db.one("SELECT * FROM feedback_items WHERE id=?", item_id)
        if not it:
            raise KeyError(f"feedback item {item_id} not found")
        cat = it["category"] if it["category"] in sp.BUGGY else "bug"
        self.db.update("feedback_items", item_id, owner_flag=1, category=cat, severity=it["severity"] or "med", updated_at=now())
        gid = self.assign_group(item_id, it["summary"] or "")
        return self.maybe_bug_intake(gid, force=True)

    # ------------------------------------------------------------------ bug fixer
    def maybe_bug_intake(self, group_id: int, force: bool = False) -> int | None:
        g = self.db.one("SELECT * FROM feedback_groups WHERE id=?", group_id)
        if not g or g["category"] not in sp.BUGGY or not g["game_id"]:
            return None
        if (g["bug_ticket_id"] or 0) > 0:
            t = self.db.one("SELECT status FROM tickets WHERE id=?", g["bug_ticket_id"])
            if t and t["status"] != "done":
                return None
            # fixed before, reported again: possible regression -> new ticket
            self.log(f"New reports for an already-fixed issue ({g['title']}): possible regression", g["game_id"], agent="support", level="warn")
        elif g["bug_ticket_id"] == 0:
            return None  # intake already queued
        if not force:
            if self.db.get("bugfix_auto_intake", "1") != "1":
                return None
            if sp.SEV_RANK.get(g["severity"] or "low", 0) < sp.SEV_RANK.get(self.db.get("bugfix_min_severity") or "med", 1):
                return None
        game = self.game(g["game_id"])
        if not game["repo_path"]:
            self.log(f"Bug report group '{g['title']}' waits: the game has no repo yet (after Gate 1)", game["id"], agent="bugfixer", level="warn")
            return None
        self.db.update("feedback_groups", group_id, bug_ticket_id=0, updated_at=now())
        return self.enqueue(game["id"], "bugfixer", "bugfix.intake", {"group_id": group_id})

    def h_bugfix_intake(self, job: dict, p: dict) -> None:
        g = self.db.one("SELECT * FROM feedback_groups WHERE id=?", p["group_id"])
        game = self.game(g["game_id"])
        items = self.db.all("SELECT * FROM feedback_items WHERE group_id=? ORDER BY id DESC LIMIT 25", g["id"])
        files = gitops.git(Path(game["repo_path"]), "ls-files").splitlines()
        reports = "\n".join(f"- #{i['id']} [{i['source']}, {i['rating'] or '-'} stars, v{i['app_version'] or '?'}, {i['device'] or '?'}] {i['text'][:600]}"
                            for i in items)
        ctx = (f"Game: {game['title']} (Godot 4.3)\nIssue group: {g['title']} ({g['category']}, severity {g['severity']}, {g['count']} reports)\n"
               f"Player reports:\n{reports}\n\nRepository files ({len(files)}):\n" + "\n".join(files[:300]) + "\n")
        data = self.call_agent(job, "bugfixer", "bugfix.intake", ctx, self.scratch(game["id"]))
        if not data.get("title") or not data.get("repro_steps"):
            from .workflow import AgentOutputError
            raise AgentOutputError("bug ticket needs title and repro_steps")
        sev = str(data.get("severity", g["severity"] or "med")).lower().replace("medium", "med")
        sev = sev if sev in sp.SEVERITIES else (g["severity"] or "med")
        desc = (f"**Expected:** {data.get('expected', '')}\n**Actual:** {data.get('actual', '')}\n"
                f"**Suspected area:** {data.get('suspected_area', '')}\n**Test plan:** {data.get('test_plan', '')}\n"
                f"**Reports:** {g['count']} (feedback group #{g['id']})")
        tid = self.db.insert("tickets", game_id=game["id"], milestone_id=None, agent="bugfixer", title=("Bug: " + str(data["title"]))[:200],
                             description=desc[:4000], status="queued", qa_loops=0, kind="bug", severity=sev,
                             repro_steps=str(data["repro_steps"])[:4000], feedback_group_id=g["id"], created_at=now(), updated_at=now())
        self.db.update("feedback_groups", g["id"], bug_ticket_id=tid, updated_at=now())
        with self.db.tx() as c:
            c.execute("UPDATE feedback_items SET bug_ticket_id=?, updated_at=? WHERE group_id=?", (tid, now(), g["id"]))
        self.add_doc(game["id"], "bug_ticket", f"Bug T#{tid}: {data['title']}", f"## Repro steps\n{data['repro_steps']}\n\n{desc}", "bugfixer")
        self.log(f"Bug ticket T#{tid} created from {g['count']} player report(s): {data['title']}", game["id"], tid, "bugfixer")
        self.enqueue(game["id"], "bugfixer", "ticket.work", {}, ticket_id=tid)

    def bug_reports_text(self, t: dict) -> str:
        rows = self.db.all("SELECT * FROM feedback_items WHERE bug_ticket_id=? ORDER BY id DESC LIMIT 10", t["id"])
        return "\n".join(f"- [{r['rating'] or '-'} stars, v{r['app_version'] or '?'}, {r['device'] or '?'}] {r['text'][:400]}" for r in rows) or "(none linked)"

    def linked_item_ids(self, tid: int) -> list[int]:
        return [r["id"] for r in self.db.all("SELECT id FROM feedback_items WHERE bug_ticket_id=?", tid)]

    def bug_qa_checks(self, repo: Path, wt: Path, t: dict, changed: list[str], godot: str | None, rep, p: dict) -> None:
        tests = [f for f in changed if re.match(r"^tests/test_.*\.gd$", f) and (wt / f).exists()]
        if not tests:
            if (p.get("no_test_reason") or "").strip():
                rep.add("bug fix has a regression test", None, "no test: " + p["no_test_reason"])
            else:
                rep.add("bug fix has a regression test", False, f"add tests/test_bug_t{t['id']}_*.gd that fails without the fix")
            return
        rep.add("bug fix has a regression test", True, ", ".join(tests))
        if not godot:
            rep.add("regression test fails on main (reproduces the bug)", None, "Godot not found")
            return
        from .godot import _run
        tmp = Path(tempfile.mkdtemp(prefix="bugrepro-"))
        probe = tmp / "main"
        try:
            gitops.git(repo, "worktree", "add", "-q", "--detach", str(probe), "main")
            for f in tests:
                (probe / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(wt / f, probe / f)
            _run([godot, "--headless", "--path", ".", "--import"], probe, 300)
            code, out = _run([godot, "--headless", "--path", ".", "-s", "res://tests/run_tests.gd"], probe, 300)
            m = re.search(r"RESULT total=(\d+) failures=(\d+)", out)
            fails = code != 0 or (m and m.group(2) != "0") or "SCRIPT ERROR" in out
            rep.add("regression test fails on main (reproduces the bug)", bool(fails),
                    "" if fails else "the new test also passes on main, so it does not reproduce the reported bug:\n" + out)
        finally:
            gitops.git(repo, "worktree", "remove", "--force", str(probe), check=False)
            shutil.rmtree(tmp, ignore_errors=True)
            gitops.git(repo, "worktree", "prune", check=False)

    def on_bug_merged(self, t: dict, sha: str) -> None:
        with self.db.tx() as c:
            n = c.execute("UPDATE feedback_items SET fixed_sha=?, updated_at=? WHERE bug_ticket_id=?", (sha, now(), t["id"])).rowcount
        self.log(f"Bug fix T#{t['id']} merged; {n} player report(s) marked fixed. Support drafts 'fixed in vX' replies after the next release.",
                 t["game_id"], t["id"], "bugfixer")

    def queue_fixed_replies(self, game_id: int, version: str = "") -> int | None:
        rows = self.db.all("SELECT id FROM feedback_items WHERE game_id=? AND fixed_sha IS NOT NULL AND (fixed_in_version IS NULL OR fixed_in_version='') "
                           "AND category<>'abuse' AND status NOT IN ('ignored')", game_id)
        if not rows:
            return None
        return self.enqueue(game_id, "support", "support.fixed_replies", {"item_ids": [r["id"] for r in rows], "version": version})

    def h_support_fixed_replies(self, job: dict, p: dict) -> None:
        rows = self._items(p.get("item_ids") or [])
        if not rows:
            return
        ver = (p.get("version") or "").strip() or "the latest update"
        ver = ver[1:] if ver.lower().startswith("v") else ver
        ctx = f"Game: {self._gtitle(job['game_id'])}\nFixed in version: {ver}\n\n" + self._items_block(rows) + "\n"
        data = self.call_agent(job, "support", "support.fixed_replies", ctx, self.scratch(job["game_id"] or 0))
        got = {}
        for r in data.get("replies") or []:
            try:
                got[int(r.get("id"))] = str(r.get("reply_draft") or "").strip()
            except (TypeError, ValueError):
                continue
        for r in rows:
            reply = got.get(r["id"]) or f"Good news: this is fixed in v{ver}. Please update the game and let us know if it still happens."
            self.db.update("feedback_items", r["id"], reply_draft=reply[:4000], fixed_in_version=ver,
                           status="reply_drafted", updated_at=now())
            if self.db.get("support_reply_to_gate6", "1") == "1":
                self.request_reply_approval(r["id"])
        self.log(f"Drafted {len(rows)} 'fixed in v{ver}' follow-up repl(ies) for Gate 6", job["game_id"], agent="support")

    # ------------------------------------------------------------------ views
    def feedback_digest(self, gid: int) -> str:
        day = now() - 86400
        cats = self.db.all("SELECT category, COUNT(*) n FROM feedback_items WHERE game_id=? AND ingested_at>=? GROUP BY category", gid, day)
        open_bugs = self.db.all("SELECT id, title, status, severity FROM tickets WHERE game_id=? AND kind='bug' AND status<>'done'", gid)
        waiting = self.db.one("SELECT COUNT(*) n FROM feedback_items WHERE game_id=? AND status='awaiting_approval'", gid)["n"]
        untriaged = self.db.one("SELECT COUNT(*) n FROM feedback_items WHERE game_id=? AND category IS NULL", gid)["n"]
        return ("Player feedback (last 24 h): " + (", ".join(f"{r['n']} {r['category'] or 'untriaged'}" for r in cats) or "none")
                + f"\nReplies waiting for Gate 6: {waiting}; untriaged: {untriaged}"
                + "\nOpen bug tickets from players:\n" + ("\n".join(f"- T#{b['id']} [{b['severity']}] {b['title']} :: {b['status']}" for b in open_bugs) or "- none"))

    def feedback_query(self, game_id: int | None = None, status: str = "", category: str = "", severity: str = "",
                       source: str = "", q: str = "", bug: str = "", limit: int = 200) -> dict:
        where, args = [], []
        if game_id == 0:
            where.append("f.game_id IS NULL")
        elif game_id:
            where.append("f.game_id=?"); args.append(game_id)
        for col, val in (("status", status), ("category", category), ("severity", severity), ("source", source)):
            if val:
                if val == "untriaged" and col == "category":
                    where.append("f.category IS NULL")
                else:
                    where.append(f"f.{col}=?"); args.append(val)
        if bug == "linked":
            where.append("f.bug_ticket_id IS NOT NULL AND f.fixed_sha IS NULL")
        elif bug == "fixed":
            where.append("f.fixed_sha IS NOT NULL")
        if q:
            where.append("(f.text LIKE ? OR f.summary LIKE ? OR f.author LIKE ?)"); args += [f"%{q}%"] * 3
        w = ("WHERE " + " AND ".join(where)) if where else ""
        items = self.db.all(f"SELECT f.*, g.title AS game_title, t.status AS ticket_status, fg.title AS group_title, fg.count AS group_count "
                            f"FROM feedback_items f LEFT JOIN games g ON g.id=f.game_id LEFT JOIN tickets t ON t.id=f.bug_ticket_id "
                            f"LEFT JOIN feedback_groups fg ON fg.id=f.group_id {w} ORDER BY f.id DESC LIMIT ?", *args, max(1, min(limit, 1000)))
        for it in items:
            it.pop("raw_json", None)
        counts = {
            "status": {r["k"]: r["n"] for r in self.db.all("SELECT status k, COUNT(*) n FROM feedback_items GROUP BY status")},
            "category": {(r["k"] or "untriaged"): r["n"] for r in self.db.all("SELECT category k, COUNT(*) n FROM feedback_items GROUP BY category")},
            "source": {r["k"]: r["n"] for r in self.db.all("SELECT source k, COUNT(*) n FROM feedback_items GROUP BY source")},
            "total": self.db.one("SELECT COUNT(*) n FROM feedback_items")["n"],
        }
        groups = self.db.all("SELECT fg.*, g.title AS game_title, t.status AS ticket_status FROM feedback_groups fg LEFT JOIN games g ON g.id=fg.game_id "
                             "LEFT JOIN tickets t ON t.id=fg.bug_ticket_id WHERE fg.count>0 ORDER BY fg.count DESC, fg.id DESC LIMIT 50")
        for gr in groups:
            gr.pop("tokens", None)
        return {"items": items, "counts": counts, "groups": groups, "categories": sp.CATEGORIES, "statuses": sp.STATUSES,
                "severities": sp.SEVERITIES, "sources": ["play", "inbox", "ingame", "imap"],
                "inbox_dir": str(self.feedback_dir()), "imap": {"enabled": self.db.get("feedback_imap_enabled") == "1",
                                                                  "configured": sp.imap_config() is not None},
                "last_scan": float(self.db.get("last_feedback_scan") or 0)}
