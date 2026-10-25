# AI Game Studio (local)

A one-person game company that runs on your MacBook. Nine AI agents do the work; you are the only
approver. Nothing passes a gate until you click **Approve** in the dashboard at http://localhost:8787
(it works on your phone's browser too if you open it on the Mac; it is bound to 127.0.0.1 only).

| Agent | Does |
|---|---|
| Producer | Turns your goal into milestones and tickets, routes work, writes the daily standup |
| Game Designer | Concept pitches, GDD, levels, economy and monetization docs |
| Engineer | Godot 4.3 GDScript in the game repo, on its own branch, with tests |
| Artist | SVG/procedural placeholder art, UI, icons, prompt sheets for final art |
| QA | Headless Godot import + unit tests + smoke run, Android Gradle export at release, bug reports |
| Marketing | Store listing, screenshot plan, trailer script, social posts (drafts only) |
| Analyst | Reads the review/crash/revenue exports you drop in and proposes next steps |
| Customer Support | Ingests player feedback (Play reviews CSV, inbox folder, IMAP, in-game JSON), de-duplicates, classifies, groups, drafts replies (Gate 6, drafts only) |
| Bug Fixer | Turns bug/crash reports into a ticket with repro steps, writes a failing test, fixes it on its own branch, QA, Gate 3 |

## The six gates

| Gate | What waits for you | Approve does | Reject (note required) does |
|---|---|---|---|
| 1 | New game concept | Creates `games/<slug>` git repo, Producer plans | Designer re-pitches using your note |
| 2 | Milestone plan (also Analyst follow-ups) | Creates tickets, starts milestone 1 | Producer re-plans using your note |
| 3 | Each code/asset change, with diff + QA report | Merges exactly the reviewed commit into `main` | Ticket goes back to its agent with your note |
| 4 | Any money spend | Records it as approved in the ledger (you buy it yourself) | Ledger entry rejected |
| 5 | Store release | Marks the game released (you upload in Play Console) | Marketing redoes the release kit |
| 6 | Anything public (social posts, review replies, emails to players) | Saves the approved text (you post or send it) | Marketing / Support redrafts using your note |

Every rejection note is also stored as feedback for that agent and included in its later prompts for that game.
The studio never pays, posts, uploads, pushes to a remote, sends email, or creates accounts.
Operating docs shared with the Hark edition (roles, gates, the launch-audit and research-before-building rules)
are in `docs/hark-edition/` (start with `OVERVIEW.md`). Prior art studied for new parts is listed in `CREDITS.md`.

---

## Dashboard tour

Plain HTML/CSS/JS served by the app (no build step, nothing loaded from the internet). Desktop shows a sidebar;
on a phone-width screen it becomes a bottom tab bar. Screens refresh every 4 seconds without wiping a form you
are editing.

| Page | What you do there |
|---|---|
| **Status** | Every agent with its live state (idle / running / queued / paused / error / disabled), current job and game, last run time and result summary (click the run to see prompt + output), queue length, jobs in backoff, engine rate-limit backoff with time left, approvals waiting per gate, today's runs/tokens vs caps, work/quiet hours |
| **Approvals** | The Approval Desk: Gates 1-6 with diff + QA report (Gate 3), spend vs budget (Gate 4), store listing (Gate 5), posts and player replies (Gate 6; edit the reply before approving). Reject always needs a note |
| **Games** | Start a new game, set a game's version (used for "fixed in vX" replies), standup now, Analyst upload, the ticket board (bug tickets are marked) |
| **Feedback** | Customer Support inbox: KPIs, filters (game, status, category, severity, source, bug link, search), per-item status, reply draft editor, Send to Gate 6, Copy + Mark posted after approval, Send to Bug Fixer, link to a game, ignore/close; top issue groups with their bug ticket |
| **Agents** | Per agent: enable/disable, pause/resume, engine + model + effort, Run now on a game (jumps the queue), edit its prompt file in the browser with Save and Reset to default (also `_common.md`), view and forget its rejection-feedback memory. Pause all / Resume all |
| **Docs & ledger** | Agent documents, spend ledger (Mark spent), jobs (Retry now), activity log |
| **Settings** | Grouped: engines, model defaults, Godot & Android paths, schedule (standup time, work hours, quiet hours), queue & limits (concurrency, backoff, daily run/token caps), budget caps, feedback sources, notifications. Values are validated. Secrets are only shown as *set / not set* |

Try it with fake data, without touching your real studio: `./run.sh demo` (http://127.0.0.1:8788, throw-away
data in a temp folder; add `--live` to let the fake agents keep working).

Engine precedence per run: `role_engines[task]` > the agent's engine on the Agents page > chore engine for chore
tasks > `role_engines[role]` > the global engine. An agent's model overrides that engine's model setting; effort
only applies to `agy`.

Scheduling: `concurrency` 1-4 parallel runs, but never two runs on the same game (so two agents never touch
one repo at once). Outside `work_hours`, or once `daily_run_cap` / `daily_token_cap` is reached, no new run starts
(the header says why). Quiet hours only silence notifications. Notifications are macOS banners
(`notify_desktop`) and, if you want, a POST to your own private channel in `STUDIO_NOTIFY_WEBHOOK`.

---

## Customer Support and Bug Fixer

### Feedback sources (set up once)
1. **Google Play reviews CSV**: Play Console > Download reports > Reviews > pick the month. Drop the
   `reviews_<package>_YYYYMM.csv` file (UTF-16 as Google ships it) into `feedback/`, or click **Upload file** on
   the Feedback page. Re-dropping a newer month or an updated file is fine: known reviews are matched by their
   review link, and edited reviews are re-triaged.
2. **Inbox folder** `feedback/` (Settings > `feedback_inbox_dir`): `.txt` (one message, or several separated by a
   `---` line; optional header lines `From:`, `Game:`, `Version:`, `Rating:`, `Device:`, `Type:`), `.json`, `.csv`
   (columns like message/text, rating, version, game, author). A sub-folder named after a game slug links the
   files to that game, e.g. `feedback/orbit-hopper/mail.txt`.
3. **In-game feedback JSON**: drop files like
   `{"game":"orbit-hopper","version":"1.0.3","items":[{"message":"...","type":"bug","device":"...","log":"..."}]}`
   into `feedback/`, or `POST /api/feedback/ingame` the same JSON from a local script (header `X-Studio: 1`).
   (The dashboard is local only, so phones cannot post to it directly; export from your backend and drop the file.)
4. **IMAP mailbox (optional)**: put `STUDIO_IMAP_HOST/PORT/USER/PASSWORD` in `.env` (for Gmail an app password),
   then Settings > `feedback_imap_enabled` = on. The folder is opened read-only and messages are fetched with
   `BODY.PEEK`, so nothing is marked read, moved or answered.
5. **Linking to games**: by package name (generated games use `com.ottranstudios.<slug>`), slug, sub-folder, the
   game's title in an email subject, or `feedback_game_map` (e.g. `{"com.ferryout.game":"ferry-out","ferry":"ferry-out"}`).
   Unlinked items can be linked on the Feedback page.

Sources are scanned every `feedback_poll_minutes` (only when there are new or changed files, or IMAP is on),
on **Scan sources now**, after an upload, and by **Run now** on the Support agent.

### What Support does
Parsing, de-duplication (normalised-text fingerprint + review link / Message-ID) and grouping (token similarity
within the same game and category family) are plain code, so they are repeatable. The Support agent classifies
each item (bug / crash / feature request / praise / billing / ads / abuse / other), sentiment and severity, writes a
one-line summary, and drafts a reply; invalid labels fall back to a rule-based classifier. Abuse gets no reply.
Every reply draft becomes a **Gate 6** approval (Settings `support_reply_to_gate6`); one pending reply per player
(a newer draft replaces the waiting one). Approving does not post: copy it into Play Console or your mail client,
then click **Mark posted**. Rejecting with a note makes Support redraft, and the note joins its feedback memory.

### What the Bug Fixer does
A bug/crash group at or above `bugfix_min_severity` (default `med`), or any item you **Send to Bug Fixer**, becomes
a bug ticket (repro steps, expected/actual, suspected files, test plan). The Bug Fixer then works test-first on its
own branch `bugfixer/t<id>-...`: a regression test `tests/test_bug_t<id>*.gd` plus the smallest fix. QA adds two
checks to the normal headless run: the fix has a regression test, and (with Godot installed) that test **fails on
`main`** in a temporary worktree, so it really reproduces the bug. Failing either sends it back. Then **Gate 3**
shows the diff + QA report with the linked player reports; only your approval merges it. After the merge the
reports are marked "fix merged"; after Gate 5 (release), or when you click **Draft "fixed in vX" replies** on the
game, Support drafts follow-ups using the game's version, again as Gate 6 drafts. Reports for an issue whose fix is
already merged open a new ticket as a possible regression.

The Producer's standup includes the last 24 h of feedback by category, replies waiting at Gate 6, and open bug
tickets from players.

---

## Important: Gemini CLI vs Antigravity CLI (read this first)

Google stopped serving **Google AI Pro / Ultra** requests through Gemini CLI's "Sign in with Google" on
**18 June 2026** and moved those plans to **Antigravity CLI (`agy`)**.
Sources: https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals and
https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli

So the default engine here is `agy`, signed in with your AI Pro Google account, called headless:

```
agy -p "<prompt>" --output-format json [--model <slug>] [--effort low|medium|high] --print-timeout 900s
```

(flags per https://antigravity.google/docs/cli/headless). The Gemini CLI adapter
(`gemini -p ... --output-format json --approval-mode auto_edit -m <model>`) is still included for API-key /
Vertex / Code Assist Standard-Enterprise auth.

Engines (pick in **Settings**; all share one adapter interface in `studio/engines.py`):

| engine | auth | edits files itself | use |
|---|---|---|---|
| `agy` (default) | Google AI Pro login (cached in macOS keychain) | yes | everything |
| `gemini_cli` | GEMINI_API_KEY / Vertex / enterprise | yes | legacy |
| `genai` | `GEMINI_API_KEY` via google-genai SDK | no (returns file blocks) | fallback |
| `ollama` | local | no | cheap chores (`chore_engine=ollama`, small models only) |
| `fake` | none | yes | tests and offline demo |

---

## Mac setup, step by step (MacBook Air M3, 16 GB)

### 1. Homebrew
If `brew --version` fails:
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Run setup
```
cd local-studio
./setup.sh --with-agy
```
It checks or installs Python 3.11+, git, and node with Homebrew, installs Antigravity CLI with Google's
installer (`curl -fsSL https://antigravity.google/cli/install.sh | bash`), builds `.venv`, installs the
Python deps, creates `.env`, and runs `./run.sh doctor`.
Add `--with-gemini-cli` if you also want `npm install -g @google/gemini-cli`.

### 3. First run of `agy`: sign in with Google
```
agy
```
Choose **Sign in with Google**. A browser opens. Use the Google account that holds your **Google AI Pro**
subscription. The token goes into the macOS keychain. Then:
```
agy models                                              # list model slugs; put one in Settings > agy_model if you want to pin it
cd /tmp && agy -p "Reply with OK" --output-format json  # must print {"status":"SUCCESS",...}
```
If that headless test prints JSON, the studio can use it. Inside `agy`, `/usage` shows your quota.

Permissions: in headless mode `agy` lets the agent read and write files inside its working folder (the
ticket's worktree). Shell commands are soft-denied, which is what we want: QA runs Godot itself. Leave
`agy_skip_permissions=0` unless you know you need it.

### 4. Godot 4.3
Download **Godot 4.3 stable (macOS, standard)** from https://godotengine.org/download/archive/4.3-stable/,
unzip it, and move `Godot.app` to `/Applications`. The studio finds `/Applications/Godot*.app/Contents/MacOS/Godot`
on its own. If yours is somewhere else, set `godot_bin` in Settings.
Note: `brew install --cask godot` installs the latest 4.x, not 4.3.
Open Godot once from Finder so macOS Gatekeeper approves it.

### 5. Android export (optional, needed for Gate 5 builds)
```
brew install --cask temurin@17                 # JDK 17
brew install --cask android-commandlinetools
sdkmanager --sdk_root="$HOME/Library/Android/sdk" "platform-tools" "build-tools;34.0.0" \
  "platforms;android-34" "cmdline-tools;latest" "cmake;3.10.2.4988404" "ndk;23.2.8568313"
```
(These are the package versions Godot 4.3 asks for:
https://docs.godotengine.org/en/4.3/tutorials/export/exporting_for_android.html)

Then:
- In `.env`, set `ANDROID_HOME=$HOME/Library/Android/sdk` and `JAVA_HOME=$(/usr/libexec/java_home -v 17)` (paste the real path).
- In Godot: **Editor > Editor Settings > Export > Android**, set *Java SDK Path* and *Android SDK Path*.
- In Godot: **Editor > Manage Export Templates > Download and Install** (4.3).
- Every generated game has an `Android` preset with Gradle build on (`export_presets.cfg`). At release, QA
  runs `godot --headless --install-android-build-template --export-debug Android build/android/game-debug.apk`.
  Release signing is yours: set `GODOT_ANDROID_KEYSTORE_RELEASE_PATH/USER/PASSWORD` yourself. No keystore
  is ever created or committed.
- With no SDK, QA marks the Android step as SKIPPED instead of failing.

### 6. Run it
```
./run.sh            # dashboard + worker on http://localhost:8787 (bound to 127.0.0.1 only)
./run.sh --awake    # same, wrapped in `caffeinate -ims` so the Mac does not idle-sleep while agents work
./run.sh doctor     # toolchain check
./run.sh demo       # offline demo with fake data on http://127.0.0.1:8788 (your real data is not touched)
```
Click **Start a new game**, describe the goal, and watch the Approval Desk.

### 7. Optional: Ollama for chores
```
brew install ollama && ollama serve &   # or the Ollama app
ollama pull llama3.2:3b                 # small models only on 16 GB (3B-8B)
```
Settings: `chore_engine=ollama`, `chore_tasks=producer.standup`.

### 8. Optional: auto-start at login (launchd)
```
sed -e "s#__STUDIO_DIR__#$PWD#g" -e "s#__USER__#$USER#g" launchd/com.aigamestudio.local.plist > ~/Library/LaunchAgents/com.aigamestudio.local.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aigamestudio.local.plist
# stop:  launchctl bootout gui/$(id -u)/com.aigamestudio.local
```
Logs go to `data/logs/`.

---

## Closing the lid, sleep, restarts

- Everything is in SQLite (`data/studio.db`, WAL mode): games, tickets, approvals, jobs, run logs, ledger,
  feedback. Git repos live in `games/<slug>`, ticket worktrees in `data/worktrees/`.
- Closing the lid sleeps the Mac and pauses everything, including an agent run in progress. On wake the
  process continues. If the process died, jobs still marked `running` go back in the queue when it restarts,
  and branches and worktrees are reused.
- `caffeinate` (`./run.sh --awake`) only prevents idle sleep with the lid open. Closing the lid still sleeps
  a MacBook unless it is in clamshell mode with power and an external display.

## Rate limits and the queue

- One agent run at a time by default (`concurrency` up to 4, never two on one game), with `min_seconds_between_runs`
  (default 5 s) between engine calls. A paused or disabled agent's jobs wait in the queue.
- Failures retry with exponential backoff (`backoff_base_seconds` 30 s, up to `max_attempts` 5).
  Quota or 429 errors get a longer backoff (`ratelimit_backoff_seconds` 300 s, capped at 1 h) and never
  count as a final failure.
- If the engine is missing or signed out, the queue **pauses** itself and shows the reason in the header.
  Fix it, then click **Resume**. **Pause** works the same way by hand.
- A job that fails for good shows **Retry now** in Jobs, and its ticket moves to *Needs you*.

## How a change reaches `main`
1. The ticket gets a branch `<agent>/t<id>-<slug>` and its own `git worktree`. `main` is never checked out by agents.
2. The agent works in that folder (agy edits files directly; non-agentic engines return files that are written with path checks).
3. The studio commits. QA runs the static checks, `godot --headless --import`, `-s res://tests/run_tests.gd`, and a 120-frame smoke run, then the QA agent reviews the diff.
4. If QA fails, the bug report goes back to the agent (up to `qa_max_loops`, default 3). After that you still decide, with QA FAILED flagged.
5. Gate 3 shows the diff and QA report. Approve merges **that exact commit SHA** with `--no-ff`. A merge conflict sends the ticket back.

## Customising
- Role prompts: `prompts/*.md` (`_common.md` applies to everyone). They are re-read on every run, and editable on
  the Agents page. The shipped defaults (used by **Reset to default**) are in `studio/prompt_defaults/`.
- Output contracts (the JSON each task must return) are in `studio/prompts.py`.
- Per-role engine: Settings > `role_engines`, e.g. `{"marketing":"genai","qa.review":"agy"}`.
- `GEMINI.md` / `AGENTS.md` in each game repo hold the project rules that agy and Gemini CLI load automatically.

## Tests
```
. .venv/bin/activate && pytest                     # fake engine, full loop
GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot pytest   # also runs real headless Godot checks
```
The tests cover new game > pitch > reject with note > re-pitch > Gate 1 > plan > Gate 2 > ticket > engineer
change on a branch > QA > Gate 3 > merge > release build > Gate 5/6. They also cover the QA bounce-back loop,
a Gate 3 rejection, a Gate 4 spend, a non-agentic engine, path traversal refusal, the analyst inbox,
rate-limit backoff, retry then fail, pause on a missing engine, resume after a crash, the HTTP API and
CSRF header, and the CLI adapters against stub binaries.
New in this version: the Status / Agents / Settings / Feedback APIs (pause, disable, engine/model/effort overrides,
run-now, prompt edit + reset, feedback memory, settings validation, secrets never returned), work hours, daily caps,
one-run-per-game concurrency guard, engine backoff state, standup time, notifications and quiet hours; Support
ingestion of a UTF-16 Play CSV, txt/json/csv inbox files, in-game JSON and IMAP (fake read-only server), dedup,
classification and grouping with the fake engine, Gate 6 reply drafts, reject > redraft > edit > approve > mark posted;
and the Bug Fixer loop: intake > test-first fix > QA (with a stub Godot that proves the regression test fails on main)
> Gate 3 > merge > "fixed in vX" follow-ups, plus the bounce-back when a fix has no regression test.

## Layout
```
local-studio/
  setup.sh  run.sh  requirements.txt  .env.example  pytest.ini
  launchd/com.aigamestudio.local.plist
  prompts/            _common, producer, designer, engineer, artist, qa, marketing, analyst, support, bugfixer (.md)
  docs/hark-edition/  operating docs shared with the Hark edition (OVERVIEW.md, README, compliance, intro kit)
  CREDITS.md          prior art studied (no third-party code copied)
  studio/
    app.py            FastAPI dashboard + JSON API (127.0.0.1:8787)
    workflow.py       agents, tickets, six gates
    feedback_flow.py  Customer Support + Bug Fixer jobs (ingest, triage, replies, bug intake, fixed follow-ups)
    support.py        feedback parsers (Play CSV, txt/json/csv, IMAP), normalise/fingerprint, rule classifier
    management.py     per-agent config, run-now, prompt edit/reset, status, caps, engine backoff
    notify.py         macOS / webhook notifications with quiet hours
    demo.py           `./run.sh demo` offline demo data
    prompt_defaults/  shipped prompts for Reset to default
    worker.py         queue: one run at a time, backoff, pause/resume, crash recovery, daily standup
    engines.py        adapters: agy, gemini_cli, genai, ollama, fake
    prompts.py        prompt assembly, output contracts, JSON extraction
    gitops.py         repo, worktrees, merge of the approved SHA
    godot.py          locate Godot, headless QA, Android export
    db.py config.py __main__.py (doctor)
    static/           index.html + app.css + app.js (dashboard, no build step)
    templates/godot/  Godot 4.3 project skeleton with a headless test runner
  tests/              pytest suite
  data/  games/  feedback/   created at runtime (gitignored; feedback/ holds player data)
```

## Known limits
- The `agy` adapter follows Google's published headless docs and is tested against a stub. It has not been
  run against a live AI Pro account from here. Do step 3's `agy -p ... --output-format json` check first.
  `agy` changes quickly. If flags move, edit `AntigravityCLIEngine.command()`.
- Quota and auth errors are recognised by matching message text. An unusual wording counts as an ordinary
  failure and retries with the normal backoff.
- No image model: the Artist makes SVG and procedural placeholders plus prompt sheets.
- A Gate 4 approval only records the spend. You buy it yourself, then click **Mark spent**.
- Store upload, social posting, review replies and support emails are manual by design (Gate 6 approves the text).
- Grouping similar feedback uses word overlap plus the agent's group label, not embeddings: very differently worded
  reports of one bug can land in two groups. Re-link by flagging, or edit; nothing is auto-closed.
- The Play Publisher reviews API (live replies, last 7 days) is not used: the studio reads the monthly CSV export and
  never posts replies.
- The "regression test fails on main" check needs a real Godot; without it the check is reported as skipped.
- Single user, local only. There is no login on the dashboard. It binds to 127.0.0.1, and every POST needs
  the `X-Studio` header.
- On a 16 GB Mac, keep Ollama models at 8B or smaller, and prefer `agy` for anything that writes code.
