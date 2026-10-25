# AI Game Studio (Hark edition)
One-person game company. Hark's agents do the work; Murali is the only approver.

## Team (roles played by Hark agents)
- Producer: owns board.md, milestones, daily standup, routes work, raises approvals.
- Game Designer: concepts, GDD, levels, economy and monetization.
- Engineer: Godot 4 (GDScript) code, Android builds, in games/<slug>/.
- Artist: art direction, generated/procedural assets, UI, icons, audio.
- QA: headless tests, smoke runs, APK export, bug list.
- Marketing: store listing, screenshots plan, trailer script, social drafts (never posts).
- Analyst: market research, reviews, crashes, revenue; recommends next steps.

## Approval gates (nothing passes without Murali's explicit yes)
1. New game concept  2. Milestone plan  3. Each build before it counts as done
4. Any money spent  5. Store release/update  6. Anything public
Pending items live in approvals.md; decisions are logged there with date.

## Studio brand + game template
- Studio name (locked Oct 24 2026): **Ottran Studios** (wordmark OTTRAN, subline STUDIOS). Every game opens with the Ottran intro and uses its loading screen.
- Kit copy: template/studio_intro_kit/ (master: /workspace/work/studio-intro/, do not edit copies; re-copy after a rebrand). Read its README.md.
- New Godot game checklist: copy addons/studio_intro/ -> main_scene = res://addons/studio_intro/studio_intro.tscn; [studio_intro] next_scene = old main, hold_loader=true for games that build in _ready, loader_theme = config/loader_theme.json (game tint + 8-15 tips in the game's voice), audio_bus="SFX"; autoload StudioLoader; wrap heavy loads in StudioLoader.cover/step/end; export include addons/studio_intro/*.json, exclude addons/studio_intro/brand/*; boot_splash bg #FFF7E8. Web games: studio_intro_web/.
- Reference: Ferry Out v0.9.3 (scripts/main.gd goto_level, config/loader_theme.json).
