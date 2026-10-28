---
title: "AI Game Studio (local): model setup guide"
subtitle: "MacBook Air M3, 16 GB - every provider, step by step"
date: "Checked against the providers' official docs on 28 October 2026"
---

# Before you start

This guide sets up the AI models the studio's nine agents use. You can give every agent the same model, or a
different one per role (for example Claude for the Engineer, Gemini for everyone else). The easiest path is the
**setup wizard** in the dashboard: run `./run.sh`, open <http://localhost:8787/#setup> and follow the eight steps.
This document explains each provider in more depth and is what the wizard links to.

**Prices, model names and limits change often.** Every figure below was read from the provider's own page on
**28 October 2026** (sources at the end). Check the page again before you rely on a number.

## The providers at a glance

| Provider (studio id) | What it is | Edits files itself | Account / key | Cost model |
|---|---|---|---|---|
| Antigravity CLI (`agy`) **default** | Google's agent CLI, signed in with your Google AI Pro account | yes | Google account login | included in Google AI Pro (quota) |
| Claude Code CLI (`claude_code`) | Anthropic's agent CLI | yes | Claude Pro/Max login, or API key | subscription limits, or per token |
| Codex CLI (`codex`) | OpenAI's agent CLI | yes | ChatGPT login, or API key | ChatGPT plan limits, or per token |
| Gemini API (`genai`) | Google's API with a key | no (returns files) | `GEMINI_API_KEY` | free tier, then per token |
| Anthropic API (`anthropic`) | Claude models by API | no | `ANTHROPIC_API_KEY` | per token, prepaid |
| OpenAI API (`openai`) | GPT models by API | no | `OPENAI_API_KEY` | per token |
| OpenRouter (`openrouter`) | one key for many providers | no | `OPENROUTER_API_KEY` | provider price + fee on credit purchases |
| Ollama (`ollama`) | local models on your Mac | no | none | free |
| LM Studio (`lmstudio`) | local models on your Mac | no | none | free |
| Gemini CLI (`gemini_cli`) | legacy; API-key use only | yes | `GEMINI_API_KEY` | per token |

"Edits files itself" matters for the Engineer, Artist and Bug Fixer: CLI agents change files in the ticket's
worktree directly; API and local models return file contents in their reply and the studio writes them (with
path checks). Both work; CLI agents are better at multi-file changes.

## Which model for which role (recommended starting points)

| Role | Best quality | Good and cheaper | Free / local |
|---|---|---|---|
| Engineer, Bug Fixer | Claude Code CLI with `claude-sonnet-5-5` (or `claude-opus-5-5` for hard tickets) | Antigravity CLI (AI Pro), Codex CLI | Ollama `qwen2.5-coder:14b` (slow, small changes only) |
| QA + Compliance | Claude Code or Codex CLI (reads the repo) | Antigravity CLI | Ollama `qwen2.5-coder:7b` |
| Producer, Designer, Artist, Marketing | Antigravity CLI (AI Pro) | Gemini API `gemini-3.8-flash` | Ollama `qwen2.5-coder:7b` |
| Customer Support, Analyst | Gemini API `gemini-3.8-flash` | `claude-haiku-5-5`, `gpt-6-luna` | Ollama `qwen2.5-coder:7b` |

The wizard's presets set these for you: **All Google AI Pro**, **Claude for engineering + Gemini for the rest**,
**Local only (Ollama)** and **Mixed**. You can change any row afterwards (wizard step 3, or the Agents page).

# 1. Antigravity CLI (default, uses your Google AI Pro subscription)

Google moved Google AI Pro / Ultra usage from Gemini CLI to Antigravity CLI on **18 June 2026**, so this is the
default engine. It costs nothing extra: usage counts against your plan's quota.

1. Install (Google's installer puts `agy` in `~/.local/bin`):
   ```
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   ```
   or run `./setup.sh --with-agy`. Open a new Terminal window afterwards.
2. Sign in once, interactively: run `agy`, choose **Sign in with Google**, and use the Google account that holds
   your AI Pro subscription. Headless runs reuse these cached credentials; a run that is not signed in exits with
   an "authentication required" error (the studio then pauses the queue and tells you).
3. Check headless mode works (this is exactly how the studio calls it):
   ```
   cd /tmp && agy -p "Reply with OK" --output-format json
   ```
   It must print one JSON object with `"status": "SUCCESS"` and a `usage` block.
4. Optional: `agy models` lists model slugs; put one in Settings > `agy_model` (empty = agy's default).
   `agy_effort` (low / medium / high) trades speed for depth.
5. In the wizard, pick **Antigravity CLI** for the roles you want and click **Test** (checks the binary) or
   **Deep test** (sends one tiny prompt).

Permissions: in headless mode agy may read and write files in its working folder (the ticket's worktree); shell
commands are soft-denied. Leave `agy_skip_permissions` off unless you know you need it.

# 2. Gemini API (API key)

Separate from Google AI Pro: it has its own free tier and pay-as-you-go billing.

1. Create a key at <https://aistudio.google.com/apikey> (sign in with any Google account).
2. Wizard step 4: paste it into **GEMINI_API_KEY**, keep **macOS Keychain** selected, click **Save**.
3. Wizard step 5: **Test** lists the models your key can see; **Deep test** sends one prompt.
4. Models (Settings > `genai_model`):
   - `gemini-3.8-flash` (default): Google's newest Flash model, recommended for new projects.
   - `gemini-3.5-flash-lite`: cheapest, for high-volume simple work (Support triage).
   - `gemini-4-argon`: flagship reasoning model, **not on the free tier**.

Pricing (per 1M tokens, paid tier, read 28 Oct 2026): `gemini-3.8-flash` $0.75 input / $3.75 output **until
31 Dec 2026, then $1.50 / $7.50**; `gemini-3.5-flash-lite` $0.30 / $2.50; `gemini-4-argon` $2 / $10 **until
30 Nov 2026, then $4 / $20**. On the free tier your prompts may be used to improve Google's products (paid tier:
not used). Google warns that 2.5-series models are now limited to existing users.

# 3. Anthropic Claude

## 3a. Claude Code CLI (recommended for the Engineer and Bug Fixer)

Requirements from Anthropic: macOS 13 or later, 4 GB+ RAM. Your M3 is fine.

1. Install with Anthropic's native installer (auto-updates):
   ```
   curl -fsSL https://claude.ai/install.sh | bash
   ```
   or `brew install --cask claude-code` (Homebrew installs do not auto-update: `brew upgrade claude-code`), or
   `./setup.sh --with-claude`. Check with `claude --version`.
2. Run `claude` once in Terminal and sign in with your Claude Pro/Max account (or a Console account / API key).
3. Headless check (how the studio calls it):
   ```
   cd /tmp && claude -p "Reply with OK" --output-format json
   ```
   The JSON has `result`, `is_error`, `usage` and an estimated `total_cost_usd`.
4. The studio passes `--permission-mode acceptEdits` for file-editing runs (Claude writes files in the worktree
   without prompting; other shell commands stay blocked) and `--allowedTools Read` for review runs.
5. Billing: by default the studio **removes `ANTHROPIC_API_KEY` from Claude Code's environment**, so Claude Code
   uses your Claude login rather than possibly billing an API key. Set Settings > `claude_use_api_key` = on only if
   you want Claude Code to bill the API key.
6. Model: Settings > `claude_model` (empty = Claude Code's default) or per role in the wizard, e.g.
   `claude-sonnet-5-5`.

## 3b. Anthropic API (key)

1. Create a key at <https://platform.claude.com> (Console > API keys) and buy prepaid credits (Gate 4: the
   studio never pays for you).
2. Wizard step 4: save it as **ANTHROPIC_API_KEY** (Keychain).
3. Models (read 28 Oct 2026 from Anthropic's models overview), per 1M tokens input / output:

| Model id | Use | Price |
|---|---|---|
| `claude-sonnet-5-5` (default) | everyday coding and writing | $2 / $10 |
| `claude-opus-5-5` | hardest coding and agent work | $4 / $20 |
| `claude-haiku-5-5` | fast, cheap classification and Support | from $0.10 / $0.50 |
| `claude-fable-5-1` | top reasoning tier | $10 / $50 |

Batch is 50% off and cached input is cheaper, but the studio sends ordinary requests. `anthropic_max_tokens`
(default 16000) caps each reply.

# 4. OpenAI

## 4a. Codex CLI

1. Install: `brew install --cask codex` (or `npm install -g @openai/codex`, or OpenAI's script
   `curl -fsSL https://chatgpt.com/codex/install.sh | sh`), or `./setup.sh --with-codex`.
2. Run `codex` once and choose **Sign in with ChatGPT** (uses your ChatGPT plan's Codex limits), or
   `codex login --with-api-key` to bill an API key instead.
3. The studio calls `codex exec --json --sandbox workspace-write -o <file> "<prompt>"` for file-editing runs and
   `--sandbox read-only` for reviews (`--full-auto` is no longer supported by Codex). For an API key in
   non-interactive runs, save **CODEX_API_KEY** and turn on Settings > `codex_use_api_key`.
4. Model: Settings > `codex_model` (empty = Codex default) or per role, e.g. `gpt-6.1-sol`.

## 4b. OpenAI API (key)

1. Create a key at <https://platform.openai.com/api-keys>; API usage is billed separately from ChatGPT plans.
2. Wizard step 4: save it as **OPENAI_API_KEY**. The studio uses the Responses API (`/v1/responses`).
3. Models (read 28 Oct 2026), per 1M tokens input / output: `gpt-6.1-sol` $2 / $10 (default, near-flagship),
   `gpt-6.1-terra` $1 / $5 (fast, efficient), `gpt-6-luna` $0.10 / $0.50 (high volume), `gpt-6-astra` $10 / $50
   (most capable). Settings > `openai_effort` sets reasoning effort.

# 5. OpenRouter (one key, many models)

1. Create a key at <https://openrouter.ai/keys> and add credits.
2. Save it as **OPENROUTER_API_KEY**. The studio calls `https://openrouter.ai/api/v1/chat/completions`.
3. Model slugs look like `anthropic/claude-sonnet-5.5` (default), `google/gemini-3.8-flash`,
   `openai/gpt-6.1-sol`. The full list is at <https://openrouter.ai/models>. `openrouter/free` routes to a free
   model.
4. Cost: OpenRouter passes through each provider's price without inference markup, and charges a fee when you buy
   credits. Free models are limited to 50 requests a day (1000 a day once you have bought at least 10 credits).

# 6. Local models (free, private, on your Mac)

16 GB of unified memory is shared by macOS, Godot, your browser and the model. Rules of thumb for this Mac:

| Model (Ollama tag) | Download | Fits on 16 GB? | Use |
|---|---|---|---|
| `qwen2.5-coder:3b` | 1.9 GB | easily | chores (standup, triage) |
| `qwen2.5-coder:7b` (default) | 4.7 GB | comfortably | all roles in the Local-only preset |
| `qwen2.5-coder:14b` | 9.0 GB | yes, with little else open (close Godot/Chrome) | Engineer / Bug Fixer |
| `qwen2.5-coder:32b` | 20 GB | **no** | - |

Local models are much weaker than the cloud models at large multi-file changes: use them for small tickets,
chores and drafts, or when you want zero cost and full privacy. Running two different local models at once
(e.g. 7B and 14B) can exceed 16 GB; pick one.

## 6a. Ollama

1. Install: download the app from <https://ollama.com/download> (needs macOS Sonoma 14 or newer), or
   `brew install ollama` / `./setup.sh --with-ollama`.
2. Start it (open the app, or `ollama serve`) and pull a model:
   ```
   ollama pull qwen2.5-coder:7b
   ```
3. Wizard: choose the **Local only (Ollama)** preset or set roles to Ollama; **Test** confirms the server is up and
   the model is pulled.
4. Context size: Ollama's default context window is only 4096 tokens, too small for studio prompts. The studio
   asks for `ollama_num_ctx` = 16384 on every request (Settings). Bigger contexts use more memory.

## 6b. LM Studio

1. Install from <https://lmstudio.ai>, download a model in the app (e.g. a Qwen2.5-Coder 7B or 14B instruct
   build) and load it.
2. Start the local server from the Developer tab, or with the CLI: `lms server start` (default port 1234).
3. The studio talks to its OpenAI-compatible endpoint `http://127.0.0.1:1234/v1`. Leave Settings >
   `lmstudio_model` empty to use whichever model is loaded, or put the model id from `GET /v1/models`.

# 7. Where keys live (and where they never go)

- **macOS Keychain** (recommended): the wizard saves each key as a generic password with service
  `ai-game-studio` and account = the variable name. View or delete it in Keychain Access, or in Terminal:
  ```
  security find-generic-password -s ai-game-studio -a ANTHROPIC_API_KEY -w
  security delete-generic-password -s ai-game-studio -a ANTHROPIC_API_KEY
  ```
  The first time the studio reads a key, macOS may ask whether `security` may access it: choose **Always Allow**.
- **`.env` file** (alternative): the wizard writes `NAME='value'` to `local-studio/.env` with permissions 600.
  The file is in `.gitignore`.
- **Lookup order:** a variable already in the environment wins, then the Keychain, then `.env`.
- Keys are **never** written to the SQLite database, prompts, logs, the dashboard (you only ever see
  `sk-a...7890`) or git. Run `./run.sh scan` before any push; it flags keys, keystores, `.env` files and builds.
- CLI logins (agy, claude, codex) are stored by those tools themselves; the studio never sees them.

# 8. Cost and usage caveats (read 28 October 2026)

| Provider | What you pay | Watch out for |
|---|---|---|
| Antigravity CLI | included in Google AI Pro | plan quota; when exhausted the studio backs off and retries later |
| Claude Code (login) | included in Claude Pro/Max | subscription usage limits |
| Claude Code (API key) | per token at Anthropic API prices | only if `claude_use_api_key` is on |
| Codex (ChatGPT login) | included in your ChatGPT plan | plan limits |
| Gemini API | free tier, then per token | price rises on 1 Dec 2026 (Argon) and 1 Jan 2027 (3.8 Flash) |
| Anthropic API | per token, prepaid credits | Opus/Fable are 2x-5x Sonnet |
| OpenAI API | per token | Astra is 5x Sol |
| OpenRouter | provider price + credit purchase fee | free models: 50 requests/day |
| Ollama / LM Studio | free | memory and speed |

Guard rails in the studio: Settings > `daily_run_cap` and `daily_token_cap` stop new runs for the day; every run
records its token count (and Claude Code's cost estimate) on the Status page. Money never moves without Gate 4.

# 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Header says **Paused: engine needs sign-in** | Run the CLI once in Terminal (`agy`, `claude`, `codex`) and sign in, then **Resume**. |
| `'agy' not found` (or claude/codex) | Open a new Terminal (PATH), or set the full path in Settings (`agy_bin`, `claude_bin`, `codex_bin`). `agy` lives in `~/.local/bin`. |
| `401` / `403` / "key missing" | Re-save the key in wizard step 4; make sure an old value in your shell environment is not overriding it (environment wins). |
| `429`, "quota", "overloaded" | Nothing to do: the studio waits `ratelimit_backoff_seconds` and retries. Lower `concurrency` or add a cheaper model for chores. |
| Ollama "model not found" / 404 | `ollama pull <model>`; check the exact tag in Settings > `ollama_model`. |
| Local model forgets the start of the prompt | Raise `ollama_num_ctx` (memory allowing). |
| LM Studio test shows 0 models | Load a model in LM Studio and start the server (`lms server start`). |
| Claude Code asks for permission / does nothing | Keep `claude_permission_mode` = `acceptEdits`; shell commands are blocked on purpose (QA runs Godot itself). |
| macOS keeps asking for Keychain access | Click **Always Allow** for `security`, or use the `.env` backend. |
| A deep test works but agent runs fail to parse | Some small local models ignore the "end with a JSON block" instruction; use a 7B+ coder model or a cloud model for that role. |
| Godot not found / 4.3 found | Install Godot 4.7.2 from <https://godotengine.org/download/macos/>, move it to /Applications, open it once (Gatekeeper). |

# 10. Sources (all opened on 28 October 2026)

- Antigravity CLI headless mode: <https://antigravity.google/docs/cli/headless>; installer script
  <https://antigravity.google/cli/install.sh>
- Gemini API models: <https://ai.google.dev/gemini-api/docs/models>; pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Anthropic models overview and prices: <https://platform.claude.com/docs/en/about-claude/models/overview>
- Claude Code setup: <https://code.claude.com/docs/en/setup>; headless: <https://code.claude.com/docs/en/headless>
- OpenAI models: <https://developers.openai.com/api/docs/models>; pricing: <https://developers.openai.com/api/docs/pricing>
- Codex CLI install: <https://github.com/openai/codex>; non-interactive mode: <https://developers.openai.com/codex/noninteractive>;
  auth: <https://developers.openai.com/codex/auth>
- OpenRouter quickstart: <https://openrouter.ai/docs/quickstart>; FAQ (fees, free limits): <https://openrouter.ai/docs/faq>;
  model list: <https://openrouter.ai/api/v1/models>
- Ollama macOS: <https://docs.ollama.com/macos>; FAQ (context length): <https://docs.ollama.com/faq>;
  Qwen2.5-Coder tags and sizes: <https://ollama.com/library/qwen2.5-coder/tags>
- LM Studio OpenAI compatibility: <https://lmstudio.ai/docs/developer/openai-compat>; `lms server start`:
  <https://lmstudio.ai/docs/cli/serve/server-start>
- Godot 4.7 Android export (JDK 17, SDK packages): <https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_android.html>
