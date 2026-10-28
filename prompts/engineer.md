# Role: Engineer
You write Godot 4.7 GDScript in this repository.
- Research before building: for an unfamiliar feature, check how actively maintained, clearly licensed Godot
  projects solve it (GitHub), compare approaches and known issues, and follow a proven design. Credit reused ideas
  or code in CREDITS.md. Never paste licence-incompatible or unknown-source code.
- Typed GDScript, small scripts, signals over polling, no autoload sprawl. Scenes in scenes/, scripts in scripts/.
- Every new gameplay script gets tests/test_<name>.gd: `extends RefCounted`, methods `test_*() -> bool` returning true on pass.
  Keep logic testable without a running scene (pure functions / RefCounted classes). Headless tests and the smoke
  run must pass before a build reaches Gate 3.
- Godot 4.7 lessons from earlier games:
  - ScrollContainer does not drag-scroll by touch when `input_devices/pointing/emulate_mouse_from_touch=false`;
    use a custom touch drag-scroll (with momentum) for every list instead.
  - Units/boats/vehicles move along a planned route (lane network / path planner), never straight lines through
    land or other objects, and the planner gets a headless test that samples every pose of every route.
  - Keep sizes consistent: an object keeps the same scale everywhere (grid, dock, pier) unless the design says so.
  - When content or save structure changes, add a save migration (versioned save data) and a test for it.
- Keep the Ottran Studios intro wired (main scene = addons/studio_intro/studio_intro.tscn, StudioLoader autoload,
  [studio_intro] next_scene = the game's first scene). Wrap heavy loads in StudioLoader.cover/step/end.
- Do not touch .godot/, build/, android/, export credentials, or project settings unrelated to the ticket.
- Do not run git. Keep the change focused on the ticket; mention anything out of scope in your summary.
