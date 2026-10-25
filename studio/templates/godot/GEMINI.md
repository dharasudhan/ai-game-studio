# Project rules for AI agents (read automatically by Antigravity CLI / Gemini CLI)

- Engine: Godot 4.3, GDScript only, typed where practical. Mobile renderer, portrait 720x1280.
- Layout: scenes/ (.tscn), scripts/ (.gd), assets/ (art/audio), docs/ (design docs), marketing/ (drafts), tests/.
- Tests: every gameplay script gets a tests/test_<name>.gd (extends RefCounted, methods test_* return true).
  Run: `godot --headless --path . -s res://tests/run_tests.gd`
- Never edit .godot/, build/, android/. Never add secrets, keystores, or network calls to paid services.
- Do not commit or switch branches; the studio handles git.
- Keep changes small and focused on the ticket.
