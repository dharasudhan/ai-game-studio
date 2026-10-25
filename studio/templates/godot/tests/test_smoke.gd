extends RefCounted

func test_main_scene_loads() -> bool:
	var scene = load("res://scenes/main.tscn")
	return scene != null

func test_main_script_instantiates() -> bool:
	var node = load("res://scenes/main.tscn").instantiate()
	var ok := node != null
	if node:
		node.free()
	return ok
