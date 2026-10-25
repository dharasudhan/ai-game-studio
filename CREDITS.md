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

## Dashboard
Plain HTML/CSS/JS written for this project (no framework, no CDN, no fonts fetched at runtime).
Python dependencies are unchanged: FastAPI, Uvicorn, python-multipart (and google-genai for the optional engine).
