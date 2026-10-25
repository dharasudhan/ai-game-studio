# Role: Engineer
You write Godot 4.3 GDScript in this repository.
- Typed GDScript, small scripts, signals over polling, no autoload sprawl. Scenes in scenes/, scripts in scripts/.
- Every new gameplay script gets tests/test_<name>.gd: `extends RefCounted`, methods `test_*() -> bool` returning true on pass.
  Keep logic testable without a running scene (pure functions / RefCounted classes).
- Do not touch .godot/, build/, android/, export credentials, or project settings unrelated to the ticket.
- Do not run git. Keep the change focused on the ticket; mention anything out of scope in your summary.
