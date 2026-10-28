extends RefCounted
## Studio rules every game keeps: the intro is the main scene, it hands over to scenes/main.tscn,
## and the legal config has a contact email and a package id.

func test_intro_is_main_scene() -> bool:
	return String(ProjectSettings.get_setting("application/run/main_scene", "")) == "res://addons/studio_intro/studio_intro.tscn"

func test_intro_hands_over_to_main() -> bool:
	var nxt := String(ProjectSettings.get_setting("studio_intro/next_scene", ""))
	return nxt == "res://scenes/main.tscn" and load(nxt) != null

func test_intro_scene_loads() -> bool:
	return load("res://addons/studio_intro/studio_intro.tscn") != null

func test_legal_config() -> bool:
	var f := FileAccess.open("res://config/legal.json", FileAccess.READ)
	if f == null:
		return false
	var d = JSON.parse_string(f.get_as_text())
	return typeof(d) == TYPE_DICTIONARY and String(d.get("package_id", "")) != "" and String(d.get("contact_email", "")).contains("@")
