# Changelog

## 1.6.0 - 2026-11-14 - Gemini Decisions API checks
- Optional setting `decisions_checks` (Settings > Engines; needs `GEMINI_API_KEY`). Uses Google's Decisions API
  (`gemini-decision-1`), which only answers yes/no, choice and score questions and bills input tokens only.
- Support triage: each player report gets a category, severity, sentiment and "needs a reply" answer. Confident
  answers win over the LLM's, and reports that need no reply (plain praise, spam) never reach the Support LLM run.
- QA screenshot pre-check: one request checks the seen-it screenshots for a blank frame, clipped text or UI under
  the HUD. A flag sends the change straight back to the Engineer, skipping the QA LLM review for that loop.
- Off by default, and skipped without a key or when a call fails, so nothing changes for 1.5.x setups. The
  "Save my AI Pro quota" preset turns it on when a Gemini key is set. It never writes code, text or replies.
- Thresholds: `decisions_min_confidence` (0.7), `decisions_fail_threshold` (0.85). Tests: 90 (6 new).

## 1.5.1 - 2026-11-13 - save my AI Pro quota
- New recommended setup preset "Save my AI Pro quota": only Engineer and Bug Fixer run on Antigravity (AI Pro).
  Producer, Designer, Artist, Marketing, Support and Analyst use the Gemini API free tier (Ollama Qwen2.5-Coder 7B
  when no GEMINI_API_KEY is set); QA uses Ollama Qwen2.5-Coder 7B.
- Applying it sets `daily_run_cap` to 40 when no cap is set yet, so runs are spread over the day. A cap you set stays.
- The wizard highlights it until you pick a preset. Existing installs: Settings > Setup wizard > Models per role.

## 1.5.0 - 2026-11-13 - automatic seen-it screenshots
- QA now opens the game in a real window on the Mac (Godot, OpenGL, 540x1170 portrait) and saves screenshots at
  3, 6 and 10 s. Tickets go to `~/.../shots/<slug>/T<id>/` and releases to `shots/<slug>/v<version>/`.
- The QA agent gets the screenshots and fails a change when anything is off-screen, clipped, overlapping or
  under the HUD. Gate 3 cards show the screenshots, or a red "No screenshots" warning.
- If Godot runs but saves no screenshot, QA fails. Without a display it's skipped. Setting: `qa_screenshots`.
- Idea taken from OhMyGame's "agent plays the game to check it". Tests: 83 (4 new).

## 1.4.1 - 2026-11-13
- Web track: melonJS is now the default engine for small 2D web games. Godot's web export is kept for 3D, heavy games and ports.

## 1.4.0 - 2026-10-28 - platform tracks
### Added
- Each game has a platform: Android (default), iOS, Roblox or Web, chosen in "Start a new game".
- `prompts/platforms/<platform>.md` is added to every agent's prompt for that game (build, store, money and
  safety rules per platform). Edit it like any other prompt file.
- Roblox games get a Rojo/Luau repo (`studio/templates/roblox`) instead of the Godot template. Godot QA is
  skipped and the owner playtests in Roblox Studio.
- The launch audit uses each platform's own rules. iOS covers Apple IAP, ATT, privacy manifest and the $99
  Apple Developer fee (Gate 4). Roblox covers Robux-only money, TextService filtering and the maturity
  questionnaire. Web covers load size, consent banner and portal SDKs. The six launch-law checks apply to all.
- Release builds for iOS, Roblox and Web are made by the owner on the Mac (Xcode, Studio, web export).
  Hark/the studio never uploads. Tests: 79 (5 new).

## 1.3.1 - 2026-10-28 - launch-law checks
### Added
- Six launch-law rows in the audit checklist: COPPA age gate, bundled fonts (no Google Fonts/CDN), session replay
  consent (CIPA/GDPR), marketing email unsubscribe + postal address (CAN-SPAM), renewal terms beside the buy button,
  and user uploads (EU DSA notice-and-action, US DMCA agent).
- Automatic checks: any runtime font/script load from Google Fonts or a public CDN is a Gate 5 blocker; a
  session-replay SDK (Hotjar, FullStory, LogRocket, Clarity...) is flagged for consent + input masking.
- The QA/Compliance prompt includes the six checks. Tests: 74 (2 new).
- Seen-it rule in the shared agent rules: a visible change only counts as done once the game has run and a
  phone-size screenshot of it is saved and checked (borrowed from Claude-Code-Game-Studios).

## 1.3.0 - 2026-10-28 - multi-model providers, setup wizard, launch-audit gate
### Added
- **Pluggable provider layer** (`studio/engines.py`): one interface (`run`, `test`, `name`, `agentic`, `model`) for
  Antigravity CLI (default), Claude Code CLI, Codex CLI, Gemini CLI (legacy), Gemini API, Anthropic API, OpenAI API
  (Responses), OpenRouter, Ollama (native `/api/chat` with a 16K context) and LM Studio (OpenAI-compatible), plus
  the mock provider for tests and the demo. Standard library only: no provider SDKs. A registry (`PROVIDERS`) holds
  each provider's label, default and suggested models, key variable, docs and a dated cost/usage note.
- **Per-role models**: each agent role picks its own provider and model (Agents page or wizard); presets "All
  Google AI Pro", "Claude for engineering + Gemini for the rest", "Local only (Ollama)", "Mixed".
- **Keys in the macOS Keychain** (service `ai-game-studio`) or the gitignored `.env` (chmod 600), lookup order
  env > Keychain > .env; the dashboard only shows masked values; keys never reach the database, prompts or logs
  (`studio/keystore.py`).
- **Test connection** per provider (binary/key/server check without tokens) and **Deep test** (one tiny prompt).
- **Guided setup wizard** (`#setup`, first run and Settings): Welcome, Prerequisites (Python, Godot 4.7, Android
  SDK, JDK 17, git, gh with fixes), Models per role, Keys, Test connections, Studio identity, GitHub & Play notes,
  Finish summary. Phone-responsive. API: `/api/setup*`, `/api/providers*`.
- **Launch-readiness audit as a workflow step** (`studio/audit.py`): runs after every release build (and on demand),
  deterministic checks + a QA/Compliance agent review, PDF with blockers first (`studio/pdfgen.py`, no
  dependencies). **Gate 5 refuses to pass** while the latest audit has blockers, is missing, or is for another
  versionCode (`audit_required_for_release`).
- **Secret scan** (`python -m studio scan`, `./run.sh scan`): keys, private keys, passwords, keystores, `.env`,
  builds. Used by the audit and before pushes.
- Studio identity settings (name, package prefix, contact email, website, GitHub owner, Play account type) used in
  prompts, new game templates, listings and audits. `docs/SETUP_MODELS.md` (+ PDF) and `docs/CHECKLISTS.md`.
### Changed
- Godot template moved to **Godot 4.7.x** with the Ottran Studios intro + loading kit wired in, package
  `<prefix>.<slug>`, target SDK 36, `config/legal.json` (contact, privacy URL, package id), `CREDITS.md`, stricter
  `.gitignore` (keystores, `.env`, AAB/APK, keys/). Verified headless with Godot 4.7.2 (6 template tests + smoke).
- Prompts carry the October 2026 lessons: research-before-building (Engineer, Bug Fixer), Godot 4.7 traps
  (drag-scroll, route planner, consistent sizes, save migrations), Play rules (12 testers x 14 days, JPEG
  screenshots, upload key, versionCode, target SDK 36, 7-day review, policy redeploy), compliance checklist,
  Gate 6 for anything public, Instagram via the Meta API, X API paid, premium visuals and compressed timelines.
- Default Ollama model `qwen2.5-coder:7b`; Gemini API default `gemini-3.8-flash`; `google-genai` dependency dropped.
- `setup.sh`: `--with-claude`, `--with-codex`, `--with-ollama`; checks for Godot 4.7.

## 1.2.0 - 2026-10-25
- Management UI (Status, Agents, Settings, Feedback), Customer Support and Bug Fixer agents, package prefix
  `com.ottranstudios.<slug>`, Hark-edition docs.

## 1.1.0 - 2026-10-24
- Default engine switched to Antigravity CLI (Google AI Pro moved off Gemini CLI on 2026-06-18).

## 1.0.0 - 2026-10-24
- First local edition: FastAPI + SQLite Approval Desk, six gates, git worktrees, Godot headless QA.
