# Credits and prior art

Studio rule: before building an unfamiliar part, look at actively maintained, clearly licensed open-source
projects for proven approaches; never copy licence-incompatible or unknown-source code; credit what is reused.

**No third-party code is copied into this repository.** The projects below were studied for design ideas only;
everything here was written from scratch.

## Customer Support / feedback triage (studied Oct 2026)
| Project | Licence | What we took (ideas only) |
|---|---|---|
| [petrkindlmann/qa-skills - ai-bug-triage](https://github.com/petrkindlmann/qa-skills) | MIT | "Deterministic first, LLM second": normalise text, fingerprint for exact de-dup, similarity scoring to group near-duplicates, LLM only for classification and ticket writing, human approval before any destructive or public action. Our `studio/support.py` normalises, fingerprints (SHA-256 prefix) and groups by token Jaccard; the agent's labels are validated against a fixed taxonomy with a rule-based fallback. |
| [Mr-Ashish/AppPulse](https://github.com/Mr-Ashish/AppPulse) | MIT | Category set for app reviews (bug, crash, feature request, praise, ...), local SQLite store, the note that the Play Publisher API only returns ~7 days of reviews so the monthly CSV export is the reliable history source. Small, young project: used as a reference, not a dependency. |
| [alexyan0431/issue-ai-agent](https://github.com/alexyan0431/issue-ai-agent) | MIT | Per-category reply intents (bugs: ask for repro details; features: acknowledge). In this studio replies are drafts that wait at Gate 6. |

Google Play reviews CSV format: columns and UTF-16 encoding per Google's Play Console Help,
"Download and export monthly reports" (https://support.google.com/googleplay/android-developer/answer/6135870).
Columns are read by name, as Google advises against depending on column positions.

## Multi-provider model layer (studied Oct 28 2026)
| Project | Licence | What we took (ideas only) |
|---|---|---|
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | MIT (outside its `enterprise/` folder) | One call shape for 100+ providers, `provider/model` addressing, OpenAI-compatible endpoints for local servers (Ollama, LM Studio), mapping provider errors (429, auth) to common exception types, a per-model price table. We did not add LiteLLM as a dependency: the studio needs one call type and must stay installable offline with the standard library. |
| [andrewyng/aisuite](https://github.com/andrewyng/aisuite) | MIT | Thin per-provider adapter classes behind one interface, discovered from a registry; providers added without touching callers. Our `PROVIDERS` registry + `build_engine()` follow that shape. |
| [simonw/llm](https://github.com/simonw/llm) | Apache-2.0 | Keys kept out of config files (environment variable or a key store, `llm keys set`), plugins for local models, the "OpenAI-compatible endpoint" escape hatch. Our key store adds the macOS Keychain and masks every value in the UI. |

Vendor documentation used for request shapes and CLI flags (checked 2026-10-28): Anthropic Messages API and
models overview, OpenAI Responses API and Codex non-interactive mode, Gemini API `generateContent`, OpenRouter
quickstart, Ollama `/api/chat` and FAQ, LM Studio OpenAI compatibility, Antigravity CLI headless mode, Claude Code
headless mode. Links are in `docs/SETUP_MODELS.md`.

## Launch audit PDF and secret scan
`studio/pdfgen.py` writes PDF 1.4 by hand from the public PDF specification (standard Type1 Helvetica, no
embedded fonts). `studio/secretscan.py` uses the token prefixes the vendors document (GitHub `ghp_`/`github_pat_`,
Google `AIza`, Anthropic `sk-ant-`, OpenAI/OpenRouter `sk-`, Slack `xox*`, AWS `AKIA`) plus private-key headers,
the same approach as gitleaks/trufflehog rules (ideas only, no rules copied).

## Godot template
The Ottran Studios intro + loading kit in `studio/templates/godot/addons/studio_intro/` is the studio's own work
(copied from the master kit). Its font, Fredoka Bold, is under the SIL Open Font License 1.1
(`addons/studio_intro/fonts/OFL.txt`); every generated game lists it in its own `CREDITS.md`.

## Dashboard
Plain HTML/CSS/JS written for this project (no framework, no CDN, no fonts fetched at runtime).
Python dependencies: FastAPI, Uvicorn, python-multipart (pytest + httpx for tests). The optional google-genai
dependency was dropped in 1.3: all providers are called with the standard library.
