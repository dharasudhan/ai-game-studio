"""The job queue worker: `concurrency` agent runs at a time (default 1, never two on the same game),
retries with backoff, pause/resume (global and per agent), work hours and daily caps, crash/sleep-safe
resume (jobs left 'running' are re-queued on start), the daily standup and the feedback scan."""
from __future__ import annotations

import random
import threading
import time
import traceback

from .db import now
from .engines import EngineUnavailable, RateLimited
from .workflow import Studio


def recover(studio: Studio) -> int:
    """Re-queue jobs interrupted by a crash, quit, or the lid closing mid-run."""
    with studio.db.tx() as c:
        n = c.execute("UPDATE jobs SET status='queued', next_run_at=?, updated_at=? WHERE status='running'",
                      (now(), now())).rowcount
    if n:
        studio.log(f"Resumed {n} unfinished job(s) after restart")
    return n


def claim_next(studio: Studio, ignore_schedule: bool = False) -> dict | None:
    blocked = studio.blocked_agents()
    with studio.db.tx() as c:
        q = ("SELECT * FROM jobs WHERE status='queued'" + ("" if ignore_schedule else " AND next_run_at<=?")
             + (f" AND (agent IS NULL OR agent NOT IN ({','.join('?' * len(blocked))}))" if blocked else "")
             # one run per game at a time, so parallel workers never touch the same repo
             + " AND (game_id IS NULL OR game_id NOT IN (SELECT game_id FROM jobs WHERE status='running' AND game_id IS NOT NULL))"
             + " ORDER BY next_run_at, id LIMIT 1")
        args = (() if ignore_schedule else (now(),)) + tuple(blocked)
        r = c.execute(q, args).fetchone()
        if not r:
            return None
        c.execute("UPDATE jobs SET status='running', started_at=?, updated_at=? WHERE id=?", (now(), now(), r["id"]))
        return dict(r)


def backoff(studio: Studio, attempts: int, rate_limited: bool) -> float:
    base = studio.db.geti("ratelimit_backoff_seconds" if rate_limited else "backoff_base_seconds", 30)
    cap = studio.db.geti("backoff_cap_seconds", 3600)
    return min(cap, base * (2 ** max(0, attempts - 1))) * random.uniform(0.85, 1.15)


def process_one(studio: Studio, ignore_schedule: bool = False) -> bool:
    """Run one queued job. Returns False when nothing was runnable."""
    if studio.db.get("paused") == "1":
        return False
    if not ignore_schedule and studio.hold_reason():
        return False
    job = claim_next(studio, ignore_schedule)
    if not job:
        return False
    db = studio.db
    studio.tl.engine = ""
    try:
        studio.handle(job)
    except EngineUnavailable as e:
        # not the job's fault: put it back untouched and pause the whole queue until the user fixes it
        db.update("jobs", job["id"], status="queued", last_error=str(e)[:2000], updated_at=now())
        db.set("paused", "1")
        db.set("pause_reason", str(e)[:500])
        studio.log(f"Queue paused: {e}", job.get("game_id"), job.get("ticket_id"), job.get("agent"), "error")
        studio.notify("errors", "Queue paused", str(e)[:200])
        return True
    except Exception as e:  # noqa: BLE001 - every failure is recorded and retried
        attempts = (job["attempts"] or 0) + 1
        rl = isinstance(e, RateLimited)
        err = f"{type(e).__name__}: {e}"
        if attempts >= (job["max_attempts"] or 5) and not rl:
            db.update("jobs", job["id"], status="failed", attempts=attempts, last_error=err[:4000],
                      finished_at=now(), updated_at=now())
            if job.get("ticket_id"):
                studio.set_ticket(job["ticket_id"], status="needs_attention")
            studio.log(f"{job['kind']} failed for good after {attempts} attempts: {err[:300]}", job.get("game_id"),
                       job.get("ticket_id"), job.get("agent"), "error")
            studio.notify("errors", f"{job['agent']} failed", f"{job['kind']}: {err[:160]}")
        else:
            delay = backoff(studio, attempts, rl)
            if rl:
                studio.set_engine_backoff(getattr(studio.tl, "engine", "") or "?", delay, err)
            db.update("jobs", job["id"], status="queued", attempts=attempts,
                      last_error=(err + "\n" + traceback.format_exc()[-1500:])[:4000], next_run_at=now() + delay, updated_at=now())
            studio.log(f"{job['kind']} {'rate-limited' if rl else 'failed'} (attempt {attempts}); retry in {int(delay)}s: {err[:200]}",
                       job.get("game_id"), job.get("ticket_id"), job.get("agent"), "warn")
        return True
    db.update("jobs", job["id"], status="done", finished_at=now(), updated_at=now(), last_error=None)
    return True


def run_until_idle(studio: Studio, max_jobs: int = 200) -> int:
    """Synchronous drain (tests / CLI). Ignores backoff schedules, work hours and caps."""
    n = 0
    while n < max_jobs and process_one(studio, ignore_schedule=True):
        n += 1
    return n


def standup_due(studio: Studio, t: time.struct_time | None = None) -> bool:
    db = studio.db
    t = t or time.localtime()
    try:
        hh, mm = (int(x) for x in (db.get("standup_time") or "").split(":"))
    except ValueError:
        hh, mm = db.geti("standup_hour", 9), 0
    return (t.tm_hour, t.tm_min) >= (hh, mm)


def maybe_schedule_standups(studio: Studio) -> None:
    db = studio.db
    if db.get("standup_enabled") != "1" or "producer" in studio.blocked_agents():
        return
    today = time.strftime("%Y-%m-%d")
    if db.get("last_standup_date") == today or not standup_due(studio):
        return
    db.set("last_standup_date", today)
    for g in db.all("SELECT id FROM games WHERE status IN ('in_production','release_prep','release_review','released')"):
        studio.request_standup(g["id"])


def maybe_scan_feedback(studio: Studio, force: bool = False) -> int | None:
    db = studio.db
    if db.get("feedback_auto_ingest") != "1" or "support" in studio.blocked_agents():
        return None
    if not force and now() - float(db.get("last_feedback_scan") or 0) < db.geti("feedback_poll_minutes", 30) * 60:
        return None
    if db.one("SELECT id FROM jobs WHERE kind='support.ingest' AND status IN ('queued','running')"):
        return None
    db.set("last_feedback_scan", str(int(now())))
    if db.get("feedback_imap_enabled") == "1" or studio.has_new_feedback_files():
        return studio.enqueue(None, "support", "support.ingest", {"reason": "scheduled scan"})
    return None


def retry_job(studio: Studio, job_id: int) -> None:
    j = studio.db.one("SELECT * FROM jobs WHERE id=?", job_id)
    if not j or j["status"] not in ("failed", "queued"):
        raise ValueError("only failed or waiting jobs can be retried")
    studio.db.update("jobs", job_id, status="queued", attempts=0, next_run_at=now(), updated_at=now())
    if j.get("ticket_id"):
        studio.set_ticket(j["ticket_id"], status="queued")


class Worker(threading.Thread):
    """Scheduler thread + `concurrency` runner threads (re-read every tick, 1-4)."""

    def __init__(self, studio: Studio, poll: float = 2.0):
        super().__init__(daemon=True, name="studio-worker")
        self.studio, self.poll = studio, poll
        self.stop_event = threading.Event()
        self.runners: list[threading.Thread] = []

    def _runner(self, idx: int) -> None:
        while not self.stop_event.is_set():
            if idx >= self.wanted():
                self.stop_event.wait(self.poll)
                continue
            try:
                if not process_one(self.studio):
                    self.stop_event.wait(self.poll)
            except Exception as e:  # never let a runner die
                self.studio.log(f"worker error: {e}", level="error")
                self.stop_event.wait(5)

    def wanted(self) -> int:
        return max(1, min(4, self.studio.db.geti("concurrency", 1)))

    def run(self) -> None:
        recover(self.studio)
        for i in range(4):
            th = threading.Thread(target=self._runner, args=(i,), daemon=True, name=f"studio-runner-{i}")
            th.start()
            self.runners.append(th)
        last_tick = 0.0
        while not self.stop_event.is_set():
            try:
                if time.time() - last_tick > 60:
                    last_tick = time.time()
                    maybe_schedule_standups(self.studio)
                    maybe_scan_feedback(self.studio)
            except Exception as e:  # never let the scheduler die
                self.studio.log(f"scheduler error: {e}", level="error")
            self.stop_event.wait(self.poll)

    def stop(self) -> None:
        self.stop_event.set()
