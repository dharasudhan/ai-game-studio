# Project rules for AI agents (read automatically by Antigravity CLI / Gemini CLI / Claude Code / Codex)

- Studio: {{STUDIO}}. Package id {{PACKAGE}} (never change it after the first Play upload). Contact {{CONTACT}}.
- Engine: Godot 4.7.x, GDScript only, typed where practical. Mobile renderer, portrait 720x1280.
- The {{STUDIO}} intro + loading screen (addons/studio_intro) stays wired: main scene = the intro,
  [studio_intro] next_scene = res://scenes/main.tscn, autoload StudioLoader. Do not edit the addon.
- Layout: scenes/ (.tscn), scripts/ (.gd), assets/ (art/audio), docs/ (design docs), marketing/ (drafts), tests/,
  config/ (legal.json, loader_theme.json).
- Tests: every gameplay script gets a tests/test_<name>.gd (extends RefCounted, methods test_* return true).
  Run: `godot --headless --path . -s res://tests/run_tests.gd`. Tests + smoke must pass before Gate 3.
- Research proven, clearly licensed open-source designs before building unfamiliar features; credit in CREDITS.md.
- Lessons: custom touch drag-scroll for lists (ScrollContainer breaks with emulate_mouse_from_touch=false);
  moving units follow a tested route planner; consistent object sizes; save migrations when content changes.
- Never edit .godot/, build/, android/. Never add secrets, keystores, or network calls to paid services.
- Do not commit or switch branches; the studio handles git.
- Keep changes small and focused on the ticket.
