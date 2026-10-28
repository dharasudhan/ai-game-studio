"""SQLite persistence. Every piece of state lives here so a restart (or a closed lid) loses nothing."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, goal TEXT NOT NULL,
  status TEXT NOT NULL, repo_path TEXT NOT NULL, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY, game_id INTEGER, kind TEXT, title TEXT, content TEXT, agent TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, game_id INTEGER, gate INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT,
  summary TEXT, payload_json TEXT, status TEXT NOT NULL DEFAULT 'pending', note TEXT,
  ref_type TEXT, ref_id INTEGER, agent TEXT, created_at REAL, decided_at REAL);
CREATE TABLE IF NOT EXISTS milestones (
  id INTEGER PRIMARY KEY, game_id INTEGER, idx INTEGER, title TEXT, goal TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY, game_id INTEGER, milestone_id INTEGER, agent TEXT, title TEXT,
  description TEXT, status TEXT, branch TEXT, worktree TEXT, qa_loops INTEGER DEFAULT 0,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, game_id INTEGER, ticket_id INTEGER, agent TEXT, kind TEXT NOT NULL,
  payload_json TEXT, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER DEFAULT 0,
  max_attempts INTEGER DEFAULT 5, next_run_at REAL DEFAULT 0, last_error TEXT,
  created_at REAL, updated_at REAL, started_at REAL, finished_at REAL);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, job_id INTEGER, game_id INTEGER, agent TEXT, task TEXT, engine TEXT,
  model TEXT, prompt TEXT, output TEXT, status TEXT, error TEXT, tokens INTEGER DEFAULT 0,
  started_at REAL, finished_at REAL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, game_id INTEGER, ticket_id INTEGER, agent TEXT, level TEXT,
  message TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY, game_id INTEGER, agent TEXT, gate INTEGER, note TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY, game_id INTEGER, approval_id INTEGER, description TEXT, vendor TEXT,
  amount REAL, currency TEXT, status TEXT, agent TEXT, created_at REAL, decided_at REAL);
CREATE TABLE IF NOT EXISTS agents (
  name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, paused INTEGER NOT NULL DEFAULT 0,
  engine TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', effort TEXT NOT NULL DEFAULT '', updated_at REAL);
CREATE TABLE IF NOT EXISTS feedback_items (
  id INTEGER PRIMARY KEY, game_id INTEGER, source TEXT NOT NULL, source_ref TEXT, external_id TEXT,
  fingerprint TEXT NOT NULL, author TEXT, rating INTEGER, language TEXT, device TEXT, app_version TEXT,
  title TEXT, text TEXT NOT NULL, submitted_at REAL, ingested_at REAL, category TEXT, sentiment TEXT,
  severity TEXT, summary TEXT, group_id INTEGER, status TEXT NOT NULL DEFAULT 'new', reply_draft TEXT,
  reply_channel TEXT, reply_approval_id INTEGER, bug_ticket_id INTEGER, fixed_sha TEXT, fixed_in_version TEXT,
  owner_flag INTEGER DEFAULT 0, duplicates INTEGER DEFAULT 0, raw_json TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS feedback_groups (
  id INTEGER PRIMARY KEY, game_id INTEGER, category TEXT, title TEXT, tokens TEXT, severity TEXT,
  count INTEGER DEFAULT 0, bug_ticket_id INTEGER, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS audits (
  id INTEGER PRIMARY KEY, game_id INTEGER, version TEXT, version_code INTEGER, blockers INTEGER, todos INTEGER,
  verdict TEXT, items_json TEXT, markdown TEXT, pdf_path TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS ingested_files (
  path TEXT PRIMARY KEY, sha TEXT NOT NULL, items INTEGER, ingested_at REAL);
CREATE INDEX IF NOT EXISTS ix_fb_fp ON feedback_items(fingerprint);
CREATE INDEX IF NOT EXISTS ix_fb_ext ON feedback_items(source, external_id);
CREATE INDEX IF NOT EXISTS ix_fb_status ON feedback_items(status);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, next_run_at);
CREATE INDEX IF NOT EXISTS ix_approvals_status ON approvals(status);
"""

# columns added after the first release (ALTER TABLE on open, so old databases keep working)
MIGRATIONS = [
    ("runs", "summary", "TEXT"),
    ("tickets", "kind", "TEXT DEFAULT 'task'"),
    ("tickets", "severity", "TEXT"),
    ("tickets", "repro_steps", "TEXT"),
    ("tickets", "feedback_group_id", "INTEGER"),
    ("tickets", "fixed_in_version", "TEXT"),
    ("games", "version", "TEXT DEFAULT ''"),
    ("games", "package", "TEXT DEFAULT ''"),
    ("games", "version_code", "INTEGER DEFAULT 0"),
    ("games", "released_version_code", "INTEGER DEFAULT 0"),
    ("runs", "cost_usd", "REAL"),
]


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.lock = threading.RLock()
        with self.lock:
            self.conn().executescript(SCHEMA)
            for table, col, typ in MIGRATIONS:
                cols = {r["name"] for r in self.conn().execute(f"PRAGMA table_info({table})").fetchall()}
                if col not in cols:
                    self.conn().execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        with self.tx() as c:
            for k, v in DEFAULT_SETTINGS.items():
                env = os.environ.get("STUDIO_" + k.upper())
                c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, env if env is not None else v))

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.c = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    # ---- tiny helpers -------------------------------------------------
    def all(self, sql: str, *args: Any) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def one(self, sql: str, *args: Any) -> dict | None:
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def insert(self, table: str, **cols: Any) -> int:
        keys = ",".join(cols)
        qs = ",".join("?" for _ in cols)
        with self.tx() as c:
            return c.execute(f"INSERT INTO {table}({keys}) VALUES({qs})", tuple(cols.values())).lastrowid

    def update(self, table: str, row_id: int, **cols: Any) -> None:
        sets = ",".join(f"{k}=?" for k in cols)
        with self.tx() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*cols.values(), row_id))

    # ---- settings -----------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        r = self.one("SELECT value FROM settings WHERE key=?", key)
        return r["value"] if r else default

    def geti(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get(key, str(default))))
        except ValueError:
            return default

    def set(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    def settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.all("SELECT key,value FROM settings")}


def now() -> float:
    return time.time()


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default
