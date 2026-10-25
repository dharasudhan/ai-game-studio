extends SceneTree
## Minimal headless test runner (no plugins needed).
## Usage: godot --headless --path . -s res://tests/run_tests.gd
## Every tests/test_*.gd file extends RefCounted; every method named test_*
## must return true (pass) or anything else (fail; a String is shown as reason).

func _initialize() -> void:
	var total := 0
	var failures := 0
	var files: Array[String] = []
	var dir := DirAccess.open("res://tests")
	if dir:
		for f in dir.get_files():
			if f.begins_with("test_") and f.ends_with(".gd"):
				files.append(f)
	files.sort()
	for f in files:
		var script = load("res://tests/" + f)
		if script == null:
			failures += 1
			print("FAIL ", f, " (could not load)")
			continue
		var inst = script.new()
		for m in inst.get_method_list():
			var name: String = m["name"]
			if not name.begins_with("test_"):
				continue
			total += 1
			var res = inst.call(name)
			if typeof(res) == TYPE_BOOL and res:
				print("PASS ", f, "::", name)
			else:
				failures += 1
				print("FAIL ", f, "::", name, " -> ", res)
	print("RESULT total=%d failures=%d" % [total, failures])
	quit(1 if failures > 0 or total == 0 else 0)
