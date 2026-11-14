# Seen-it capture (AI Game Studio). Runs the game's main scene in a real window and saves PNG screenshots.
# godot --path . --rendering-driver opengl3 --resolution 540x1170 -s res://.studio_capture.gd -- --out=DIR
extends SceneTree

const AT_SECONDS := [3.0, 6.0, 10.0]
var out_dir := ""
var t := 0.0
var shot := 0

func _initialize() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--out="):
			out_dir = a.substr(6)
	var main: String = ProjectSettings.get_setting("application/run/main_scene", "")
	if out_dir == "" or main == "":
		printerr("CAPTURE ERROR: missing --out or main scene")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(out_dir)
	change_scene_to_file(main)

func _process(delta: float) -> bool:
	t += delta
	if shot < AT_SECONDS.size() and t >= AT_SECONDS[shot]:
		var img := root.get_texture().get_image()
		var path := "%s/shot_%02d.png" % [out_dir, shot + 1]
		if img == null or img.is_empty() or img.save_png(path) != OK:
			printerr("CAPTURE ERROR: could not save ", path)
		else:
			print("CAPTURED ", path)
		shot += 1
	if shot >= AT_SECONDS.size():
		quit(0)
	return false
