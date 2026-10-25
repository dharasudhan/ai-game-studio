extends Node
## Kit renderer (run inside the demo project, or any project with the addon):
##   MODE=frames  SIZE=1080x2400 OUT=dir FPS=30   -> intro frames f_0000.png ...
##   MODE=keys    SIZE=..        OUT=dir TIMES=0.5,1.0,2.0 -> key_<t>.png
##   MODE=logo    OUT=dir                         -> logo.png (2048x1024, transparent), mark.png (512, transparent),
##                                                   logo_bg.png (2048x1024 on the brand gradient)
##   MODE=loading SIZE=.. OUT=dir                 -> loading.png (progress 0.62)
## Run: godot --rendering-driver opengl3 --path demo res://tools/render.tscn (DISPLAY needed)

var out := "/tmp/studio_render"


func _env(k: String, d: String) -> String:
	var v := OS.get_environment(k)
	return v if v != "" else d


func _size(s: String) -> Vector2i:
	var p := s.split("x")
	return Vector2i(int(p[0]), int(p[1]))


func _ready() -> void:
	out = _env("OUT", out)
	DirAccess.make_dir_recursive_absolute(out)
	var mode := _env("MODE", "keys")
	get_tree().root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
	if mode == "mem":
		await _resize(_size(_env("SIZE", "1080x2400")))
		var base := Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)
		var intro: StudioIntro = load("res://addons/studio_intro/studio_intro.tscn").instantiate()
		intro.next_scene = ""
		add_child(intro)
		intro.seek(1.9, true)
		for i in 10:
			await get_tree().process_frame
		var a := Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)
		StudioLoader.cover(["Tip: a long enough tip line to wrap onto two lines on a phone"], {"fade": 0.0})
		for i in 20:
			await get_tree().process_frame
		var b := Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)
		print("RENDER: MEM texture MB base %.2f intro %.2f (+%.2f) intro+loader %.2f (+%.2f)" % [base / 1048576.0, a / 1048576.0, (a - base) / 1048576.0, b / 1048576.0, (b - base) / 1048576.0])
		print("RENDER: done mem")
		get_tree().quit()
		return
	if mode == "logo":
		await _logo()
	elif mode == "loading":
		await _loading()
	else:
		await _intro(mode)
	print("RENDER: done ", mode)
	get_tree().quit()


func _resize(sz: Vector2i) -> void:
	get_window().size = sz
	for i in 4:
		await get_tree().process_frame
	print("RENDER: window ", get_window().size, " viewport ", get_viewport().get_visible_rect().size)


func _grab(path: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(path)


func _intro(mode: String) -> void:
	await _resize(_size(_env("SIZE", "1080x2400")))
	var intro: StudioIntro = load("res://addons/studio_intro/studio_intro.tscn").instantiate()
	intro.next_scene = ""
	intro.play_sound = false
	add_child(intro)
	if mode == "frames":
		var fps := float(_env("FPS", "30"))
		var n := int(ceil(StudioIntro.T_END * fps))
		for f in n + 1:
			intro.seek(float(f) / fps)
			await _grab("%s/f_%04d.png" % [out, f])
	else:
		for ts in _env("TIMES", "0.6,1.05,1.75").split(","):
			intro.seek(float(ts))
			await get_tree().process_frame
			await _grab("%s/key_%s.png" % [out, ts])


class LogoDraw extends Control:
	var tt := 2.3
	var mark := false
	var with_bg := false
	func _draw() -> void:
		var r := Rect2(Vector2.ZERO, size)
		if with_bg:
			StudioDraw.bg(self, r, StudioBrand.col("bg_top"), StudioBrand.col("bg_bottom"))
		var pal := StudioDraw.palette()
		if mark:
			StudioDraw.mascot(self, Vector2(size.x * 0.5, size.y * 0.93), size.x * 0.31, {"shadow": 0.0}, pal)
		else:
			StudioIntro.draw_logo(self, tt, Rect2(size * 0.5 - size * 0.75, size * 1.5), 1.0, pal, StudioBrand.font(), StudioBrand.wordmark(), StudioBrand.mascot_slot(), String(StudioBrand.data().get("subline", "")))


func _logo() -> void:
	get_viewport().transparent_bg = true
	for job in [["logo", Vector2i(2048, 1024), false, false], ["logo_bg", Vector2i(2048, 1024), false, true], ["mark", Vector2i(512, 512), true, false]]:
		await _resize(job[1])
		var d := LogoDraw.new()
		d.mark = job[2]
		d.with_bg = job[3]
		d.size = Vector2(job[1])
		add_child(d)
		await get_tree().process_frame
		await _grab("%s/%s.png" % [out, job[0]])
		d.queue_free()
		await get_tree().process_frame


func _loading() -> void:
	await _resize(_size(_env("SIZE", "1080x2400")))
	StudioLoader.cover(["Tip: Golden Forks win the match. Most forks takes the crown!"], {"fade": 0.0})
	StudioLoader.set_progress(float(_env("PROGRESS", "0.62")))
	for i in int(_env("FRAMES", "40")):
		await get_tree().process_frame
	await _grab("%s/%s.png" % [out, _env("NAME", "loading")])
