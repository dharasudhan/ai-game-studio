"""Paths and default settings. Everything is overridable via env or the Settings panel."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .engines import ENGINE_IDS

APP_ROOT = Path(__file__).resolve().parent.parent  # local-studio/


@dataclass
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "data" / "studio.db"

    @property
    def games(self) -> Path:
        return self.home / "games"

    @property
    def worktrees(self) -> Path:
        return self.home / "data" / "worktrees"

    @property
    def scratch(self) -> Path:
        return self.home / "data" / "scratch"

    @property
    def logs(self) -> Path:
        return self.home / "data" / "logs"

    @property
    def feedback(self) -> Path:
        return self.home / "feedback"

    @property
    def prompts(self) -> Path:
        p = os.environ.get("STUDIO_PROMPTS")
        return Path(p) if p else APP_ROOT / "prompts"

    def ensure(self) -> None:
        for d in (self.db.parent, self.games, self.worktrees, self.scratch, self.logs, self.feedback):
            d.mkdir(parents=True, exist_ok=True)


def default_paths() -> Paths:
    return Paths(Path(os.environ.get("STUDIO_HOME", str(APP_ROOT))).expanduser().resolve())


# Settings live in SQLite (table `settings`) and are seeded from these defaults.
# Env vars STUDIO_<KEY upper> override the seed on first start.
DEFAULT_SETTINGS: dict[str, str] = {
    # default provider for every role (per-role overrides live on the Agents page / setup wizard):
    # agy | claude_code | codex | gemini_cli | genai | anthropic | openai | openrouter | ollama | lmstudio | fake
    "engine": "agy",
    "agy_bin": "agy",
    "agy_model": "",            # empty = CLI default; see `agy models`
    "agy_effort": "",           # low | medium | high | empty
    "agy_skip_permissions": "0",  # 1 = --dangerously-skip-permissions for file-editing agents
    "gemini_bin": "gemini",
    "gemini_model": "",
    "genai_model": "gemini-3.8-flash",                       # Gemini API (GEMINI_API_KEY)
    "gemini_api_base": "https://generativelanguage.googleapis.com/v1beta",
    "claude_bin": "claude",                                  # Claude Code CLI
    "claude_model": "",                                      # empty = Claude Code default
    "claude_permission_mode": "acceptEdits",
    "claude_use_api_key": "0",                               # 0 = use your Claude login, never ANTHROPIC_API_KEY
    "anthropic_model": "claude-sonnet-5-5",                  # Anthropic API (ANTHROPIC_API_KEY)
    "anthropic_base": "https://api.anthropic.com",
    "anthropic_max_tokens": "16000",
    "codex_bin": "codex",                                    # OpenAI Codex CLI
    "codex_model": "",
    "codex_use_api_key": "0",
    "openai_model": "gpt-6.1-sol",                           # OpenAI API (OPENAI_API_KEY)
    "openai_base": "https://api.openai.com/v1",
    "openai_effort": "",
    "openrouter_model": "anthropic/claude-sonnet-5.5",       # OpenRouter (OPENROUTER_API_KEY)
    "openrouter_base": "https://openrouter.ai/api/v1",
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_model": "qwen2.5-coder:7b",
    "ollama_num_ctx": "16384",
    "lmstudio_base": "http://127.0.0.1:1234/v1",
    "lmstudio_model": "",                                    # empty = whichever model is loaded
    # studio identity (setup wizard step 6) - used in prompts, new game templates, store listings and audits
    "studio_name": "Ottran Studios",
    "package_prefix": "com.ottranstudios",
    "contact_email": "ottranstudios@gmail.com",
    "studio_website": "https://ottranstudios.com",
    "github_owner": "",
    "play_account_type": "personal",        # personal accounts: 12 testers x 14 days closed test before production
    "play_target_sdk": "36",
    "setup_complete": "0",
    "setup_step": "welcome",
    # launch-readiness audit (blocks Gate 5)
    "audit_required_for_release": "1",
    "audit_fetch_privacy_policy": "1",      # fetch the hosted policy and check it names the final package id
    "chore_engine": "",         # e.g. "ollama" -> used for chore tasks below
    "chore_tasks": "producer.standup",
    "role_engines": "{}",       # JSON, e.g. {"marketing": "genai"}
    "godot_bin": "",
    "paused": "0",
    "pause_reason": "",
    "min_seconds_between_runs": "5",
    "max_attempts": "5",
    "backoff_base_seconds": "30",
    "ratelimit_backoff_seconds": "300",
    "backoff_cap_seconds": "3600",
    "engine_timeout_seconds": "900",
    "qa_max_loops": "3",
    "qa_android_export_on_release": "1",
    "monthly_budget": "0",
    "currency": "EUR",
    "standup_enabled": "1",
    "standup_hour": "9",           # legacy; standup_time wins when it is a valid HH:MM
    "standup_time": "09:00",
    "last_standup_date": "",
    # scheduling and limits
    "concurrency": "1",            # parallel agent runs (never two runs on the same game at once)
    "work_hours": "",              # e.g. 08:00-23:00; empty = agents may start runs any time
    "quiet_hours": "22:30-07:30",  # no notifications in this window
    "daily_run_cap": "0",          # 0 = no cap; when reached, no new runs start until tomorrow
    "daily_token_cap": "0",        # 0 = no cap
    "spend_cap_per_request": "0",  # 0 = no cap; bigger spend requests are flagged at Gate 4
    # android
    "android_sdk_path": "",        # overrides ANDROID_HOME for exports
    "java_home": "",               # overrides JAVA_HOME for exports
    "android_export_dir": "build/android",
    # customer support / feedback sources
    "feedback_inbox_dir": "feedback",       # relative to STUDIO_HOME or absolute
    "feedback_auto_ingest": "1",
    "feedback_poll_minutes": "30",
    "feedback_game_map": "{}",              # JSON {"com.pkg.name" or keyword: "game-slug"}
    "feedback_imap_enabled": "0",           # credentials come from .env only (STUDIO_IMAP_*)
    "feedback_imap_folder": "INBOX",
    "feedback_imap_search": "UNSEEN",
    "feedback_imap_max": "50",
    "support_reply_to_gate6": "1",          # drafted replies become Gate 6 approvals
    "support_batch_size": "20",
    "bugfix_auto_intake": "1",              # bug/crash groups go to the Bug Fixer automatically
    "bugfix_min_severity": "med",           # low | med | high | critical
    "last_feedback_scan": "0",
    # notifications (desktop only by default; webhook URL comes from .env)
    "notify_desktop": "1",
    "notify_webhook": "0",
    "notify_on": "approvals,errors,standup,feedback",
    "engine_backoff": "{}",
}

ENGINES = list(ENGINE_IDS)

# Settings the dashboard may edit, grouped for the Settings page. type: str|int|bool|choice|json|time|range
SETTINGS_SCHEMA: dict[str, dict] = {
    "engine": {"group": "Engines", "type": "choice", "choices": ENGINES, "help": "Default engine for every agent"},
    "chore_engine": {"group": "Engines", "type": "choice", "choices": [""] + ENGINES, "help": "Engine for cheap chore tasks (empty = off)"},
    "chore_tasks": {"group": "Engines", "type": "str", "help": "Comma list of tasks that use the chore engine"},
    "role_engines": {"group": "Engines", "type": "json", "help": 'Advanced per-role/task overrides, e.g. {"qa.review":"agy"}'},
    "agy_bin": {"group": "Engines", "type": "str", "help": "Antigravity CLI binary"},
    "claude_bin": {"group": "Engines", "type": "str", "help": "Claude Code CLI binary"},
    "claude_permission_mode": {"group": "Engines", "type": "choice", "choices": ["acceptEdits", "auto", "dontAsk"], "help": "Claude Code permission mode for file-editing runs"},
    "claude_use_api_key": {"group": "Engines", "type": "bool", "help": "Let Claude Code bill ANTHROPIC_API_KEY instead of your Claude login"},
    "codex_bin": {"group": "Engines", "type": "str", "help": "Codex CLI binary"},
    "codex_use_api_key": {"group": "Engines", "type": "bool", "help": "Give Codex CODEX_API_KEY instead of your ChatGPT login"},
    "gemini_api_base": {"group": "Engines", "type": "str", "help": "Gemini API base URL"},
    "anthropic_base": {"group": "Engines", "type": "str", "help": "Anthropic API base URL"},
    "openai_base": {"group": "Engines", "type": "str", "help": "OpenAI API base URL"},
    "openrouter_base": {"group": "Engines", "type": "str", "help": "OpenRouter base URL"},
    "lmstudio_base": {"group": "Engines", "type": "str", "help": "LM Studio OpenAI-compatible URL"},
    "agy_model": {"group": "Model defaults", "type": "str", "help": "agy model slug (see `agy models`); empty = CLI default"},
    "agy_effort": {"group": "Model defaults", "type": "choice", "choices": ["", "low", "medium", "high"], "help": "agy effort"},
    "agy_skip_permissions": {"group": "Engines", "type": "bool", "help": "--dangerously-skip-permissions for file-editing runs"},
    "gemini_bin": {"group": "Engines", "type": "str", "help": "Gemini CLI binary"},
    "gemini_model": {"group": "Model defaults", "type": "str", "help": "Gemini CLI model"},
    "genai_model": {"group": "Model defaults", "type": "str", "help": "Gemini API model"},
    "claude_model": {"group": "Model defaults", "type": "str", "help": "Claude Code model (empty = CLI default)"},
    "anthropic_model": {"group": "Model defaults", "type": "str", "help": "Anthropic API model"},
    "anthropic_max_tokens": {"group": "Model defaults", "type": "int", "help": "Anthropic max output tokens per run"},
    "codex_model": {"group": "Model defaults", "type": "str", "help": "Codex CLI model (empty = CLI default)"},
    "openai_model": {"group": "Model defaults", "type": "str", "help": "OpenAI API model"},
    "openai_effort": {"group": "Model defaults", "type": "choice", "choices": ["", "none", "low", "medium", "high"], "help": "OpenAI reasoning effort"},
    "openrouter_model": {"group": "Model defaults", "type": "str", "help": "OpenRouter model slug"},
    "lmstudio_model": {"group": "Model defaults", "type": "str", "help": "LM Studio model (empty = loaded model)"},
    "ollama_host": {"group": "Engines", "type": "str", "help": "Ollama URL"},
    "ollama_model": {"group": "Model defaults", "type": "str", "help": "Ollama model (16 GB Mac: 7B, or 14B with little else open)"},
    "ollama_num_ctx": {"group": "Model defaults", "type": "int", "help": "Ollama context window (default 4096 is too small)"},
    "studio_name": {"group": "Studio identity", "type": "str", "help": "Brand on every game intro and listing"},
    "package_prefix": {"group": "Studio identity", "type": "str", "help": "Android package prefix: <prefix>.<slug>"},
    "contact_email": {"group": "Studio identity", "type": "str", "help": "Public support email for listings and policies"},
    "studio_website": {"group": "Studio identity", "type": "str", "help": "Website on store listings (privacy policies live under it)"},
    "github_owner": {"group": "Studio identity", "type": "str", "help": "GitHub account for private game repos (you push; the studio never does)"},
    "play_account_type": {"group": "Studio identity", "type": "choice", "choices": ["personal", "organization"], "help": "Play developer account type"},
    "play_target_sdk": {"group": "Godot & Android", "type": "int", "help": "Required Android target SDK for uploads"},
    "audit_required_for_release": {"group": "Godot & Android", "type": "bool", "help": "Launch-readiness audit must pass before Gate 5"},
    "audit_fetch_privacy_policy": {"group": "Godot & Android", "type": "bool", "help": "Audit fetches the hosted privacy policy and checks the package id"},
    "engine_timeout_seconds": {"group": "Engines", "type": "int", "help": "Max seconds per agent run"},
    "godot_bin": {"group": "Godot & Android", "type": "str", "help": "Godot 4.7.x binary (empty = auto-detect)"},
    "android_sdk_path": {"group": "Godot & Android", "type": "str", "help": "Android SDK (empty = ANDROID_HOME)"},
    "java_home": {"group": "Godot & Android", "type": "str", "help": "JDK 17 home (empty = JAVA_HOME)"},
    "android_export_dir": {"group": "Godot & Android", "type": "str", "help": "Export folder inside the game repo"},
    "qa_android_export_on_release": {"group": "Godot & Android", "type": "bool", "help": "Debug APK export during release QA"},
    "qa_max_loops": {"group": "Godot & Android", "type": "int", "help": "QA bounce-backs before you decide anyway"},
    "standup_enabled": {"group": "Schedule", "type": "bool", "help": "Daily Producer standup"},
    "standup_time": {"group": "Schedule", "type": "time", "help": "Daily standup time (HH:MM, local)"},
    "work_hours": {"group": "Schedule", "type": "range", "help": "Agents start runs only in this window, e.g. 08:00-23:00 (empty = always)"},
    "quiet_hours": {"group": "Schedule", "type": "range", "help": "No notifications in this window"},
    "concurrency": {"group": "Queue & limits", "type": "int", "help": "Parallel agent runs (1-4; one per game at a time)"},
    "min_seconds_between_runs": {"group": "Queue & limits", "type": "int", "help": "Gap between engine calls"},
    "max_attempts": {"group": "Queue & limits", "type": "int", "help": "Attempts before a job fails for good"},
    "backoff_base_seconds": {"group": "Queue & limits", "type": "int", "help": "Retry backoff base"},
    "ratelimit_backoff_seconds": {"group": "Queue & limits", "type": "int", "help": "Backoff after a quota / 429"},
    "backoff_cap_seconds": {"group": "Queue & limits", "type": "int", "help": "Longest backoff"},
    "daily_run_cap": {"group": "Queue & limits", "type": "int", "help": "Max agent runs per day (0 = no cap)"},
    "daily_token_cap": {"group": "Queue & limits", "type": "int", "help": "Max tokens per day (0 = no cap)"},
    "monthly_budget": {"group": "Budget", "type": "int", "help": "Monthly spend budget (Gate 4 shows usage)"},
    "spend_cap_per_request": {"group": "Budget", "type": "int", "help": "Flag spend requests above this (0 = off)"},
    "currency": {"group": "Budget", "type": "str", "help": "Currency code"},
    "feedback_inbox_dir": {"group": "Feedback sources", "type": "str", "help": "Drop folder for Play CSV / .txt / .json / .csv"},
    "feedback_auto_ingest": {"group": "Feedback sources", "type": "bool", "help": "Scan sources automatically"},
    "feedback_poll_minutes": {"group": "Feedback sources", "type": "int", "help": "Scan interval"},
    "feedback_game_map": {"group": "Feedback sources", "type": "json", "help": 'Map package names / keywords to game slugs, e.g. {"com.ferryout.game":"ferry-out"}'},
    "feedback_imap_enabled": {"group": "Feedback sources", "type": "bool", "help": "Read a support mailbox (host/user/password from .env)"},
    "feedback_imap_folder": {"group": "Feedback sources", "type": "str", "help": "IMAP folder"},
    "feedback_imap_search": {"group": "Feedback sources", "type": "str", "help": "IMAP search, e.g. UNSEEN or SINCE 01-Oct-2026"},
    "feedback_imap_max": {"group": "Feedback sources", "type": "int", "help": "Max messages per scan"},
    "support_reply_to_gate6": {"group": "Feedback sources", "type": "bool", "help": "Drafted replies go to Gate 6 automatically"},
    "support_batch_size": {"group": "Feedback sources", "type": "int", "help": "Items per Support triage run"},
    "bugfix_auto_intake": {"group": "Feedback sources", "type": "bool", "help": "Send bug/crash groups to the Bug Fixer"},
    "bugfix_min_severity": {"group": "Feedback sources", "type": "choice", "choices": ["low", "med", "high", "critical"], "help": "Lowest severity the Bug Fixer picks up by itself"},
    "notify_desktop": {"group": "Notifications", "type": "bool", "help": "macOS notifications"},
    "notify_webhook": {"group": "Notifications", "type": "bool", "help": "Also POST to STUDIO_NOTIFY_WEBHOOK (e.g. your own ntfy topic)"},
    "notify_on": {"group": "Notifications", "type": "str", "help": "Comma list: approvals, errors, standup, feedback"},
}

# Secrets are read from the environment (.env) only. The dashboard shows set / not set, never values.
# API keys the setup wizard can save (Keychain or .env). Values never enter the database.
API_KEY_ENV = ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CODEX_API_KEY"]
SECRET_ENV = ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "STUDIO_IMAP_HOST", "STUDIO_IMAP_USER", "STUDIO_IMAP_PASSWORD",
              "STUDIO_NOTIFY_WEBHOOK", "GODOT_ANDROID_KEYSTORE_RELEASE_PATH", "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"]
