# AI Game Studio - Hark edition (operating docs)

This folder is a copy of the operating docs the studio runs on in Hark (the hosted edition). The Mac edition
in this repo follows the same roles, gates and rules; this copy is here so both editions stay in step.
Files: `README.md` (charter), `compliance.md` (compliance gate + launch-readiness audit), `template/studio_intro_kit/`
(Ottran Studios intro + loading screen kit for every Godot game). Not copied on purpose: games, the live board
and approvals log, keys, keystores, and anything containing secrets.

## Roles
One human (Murali) is the only approver. AI agents play every role:

| Role | Job |
|---|---|
| Producer | Milestones and tickets, routes work, daily standup, keeps the board and approvals current |
| Game Designer | Concept pitches (hook, loop, monetization, scope, risks), GDD after Gate 1 |
| Engineer | Godot 4 (GDScript) code and Android export, small commits on its own branch, never ships unreviewed |
| Artist | Art direction, generated/procedural assets, UI, icons, audio, within the mobile memory budget |
| QA | Headless Godot tests and smoke runs before Gate 3; device-test checklist for the owner |
| Compliance | Runs `compliance.md` and the launch-readiness audit before every store upload |
| Marketing | Store listing, screenshots plan, trailer script, social posts - drafts only |
| Analyst | Market signals, reviews, crashes, revenue; recommends next steps |
| Customer Support (Mac edition) | Ingests player feedback, classifies, groups, drafts replies - drafts only, Gate 6 |
| Bug Fixer (Mac edition) | Turns player bug/crash reports into tickets and test-first fixes, through Gate 3 |

## The six gates (hard rules)
1. New game concept  2. Milestone plan  3. Each build/change before it counts as done (diff + QA report)
4. Any money spent  5. Store release or update  6. Anything public (posts, review replies, emails to players)

A gate is presented as one clear choice with a recommendation. Only an explicit "yes" from Murali passes it.
A rejection note goes back to the agent and into its feedback memory.

## Standing rules
- **Never upload, spend, publish, post, send, or create accounts without explicit approval.** Approving a gate
  records the decision; the owner performs the upload, purchase, post or email himself. The studio never pushes
  to a remote, posts a review reply, or sends an email.
- **Launch-readiness audit PDF before any Play upload** (Murali, 25 Oct 2026). Before every closed-test or
  production upload of any app, QA + Compliance run the full audit (performance, device compatibility, Google Play
  policy, the 12-point compliance checklist) and hand Murali a PDF with PASS/FAIL/TODO per item, blockers first,
  saved as `games/<slug>/audit/launch_audit_v<version>.pdf`. No PDF, no upload.
- **Research before building** (Murali, 25 Oct 2026). For any unfamiliar feature, first look at actively
  maintained, clearly licensed open-source projects that solve it; compare approaches, dependencies and known
  issues; prefer proven designs. Never copy licence-incompatible or unknown-source code; credit anything reused
  in CREDITS.md. Every engineering brief includes this step.
- Default platform: Android (Godot 4), ads + IAP with test IDs until Gates 4/5.
- Every game opens with the Ottran Studios intro and uses its loading screen (see `template/`).
