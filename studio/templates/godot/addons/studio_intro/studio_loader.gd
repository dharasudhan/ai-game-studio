extends CanvasLayer
## Autoload "StudioLoader": the loading screen + scene hand-off helper.
##
##   StudioLoader.load_scene("res://game.tscn", ["Tip one", "Tip two"])   # threaded load, progress bar, scene change
##   await StudioLoader.cover(tips)    # just show the loading screen (procedural builds, reloads)
##   await StudioLoader.step(0.5)      # report progress + let one frame draw (no-op when not covering)
##   await StudioLoader.end()          # waits out the minimum display time, then fades away
##
## Theme per game: project setting studio_intro/loader_theme = path of a JSON file
## {"tips": [...], "title": "Loading", "colors": {bg_top, bg_bottom, bar, bar_bg, bar_outline, title, tip, bokeh},
##  "mascot": {colour overrides}, "layer": 120, "min_display": 0.4, "max_cover": 45}
## or StudioLoader.configure({...}) at runtime. Godot 4.3 .. 4.7, gl_compatibility safe.

signal covered            # the loading screen is fully on screen
signal ended              # end() finished waiting and the fade-out started

const SCREEN := "res://addons/studio_intro/studio_loading.tscn"

var tips: Array = []
var title_text := "Loading"
var min_display := 0.4
var max_cover := 45.0
var colors := {}
var mascot_over := {}

var _screen: Control
var _active := false
var _shown_ms := 0
var _fade: Tween
var _local_tips: Array = []
var _warmed := false


func _ready() -> void:
	layer = 120
	process_mode = Node.PROCESS_MODE_ALWAYS
	var p := String(ProjectSettings.get_setting("studio_intro/loader_theme", ""))
	if p != "" and FileAccess.file_exists(p):
		var j = JSON.parse_string(FileAccess.get_file_as_string(p))
		if j is Dictionary:
			configure(j)
		else:
			push_error("StudioLoader: theme %s is not valid JSON" % p)


## Theme the loading screen: tips, title, colours, mascot colour overrides, layer, timings.
func configure(d: Dictionary) -> void:
	if d.has("tips"):
		tips = Array(d.tips)
	if d.has("title"):
		title_text = String(d.title)
	if d.has("min_display"):
		min_display = float(d.min_display)
	if d.has("max_cover"):
		max_cover = float(d.max_cover)
	if d.has("layer"):
		layer = int(d.layer)
	if d.get("colors") is Dictionary:
		for k in d.colors:
			colors[k] = Color.html(String(d.colors[k]))
	if d.get("mascot") is Dictionary:
		mascot_over = d.mascot


func is_active() -> bool:
	return _active


## Seconds the loading screen has been up (0 when hidden).
func shown_for() -> float:
	return float(Time.get_ticks_msec() - _shown_ms) / 1000.0 if _active else 0.0


# ------------------------------------------------------------------ threaded loading
## Start a threaded load (no screen). Safe to call twice.
func prefetch(path: String) -> void:
	if path == "" or ResourceLoader.has_cached(path):
		return
	var st := ResourceLoader.load_threaded_get_status(path)
	if st == ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
		var err := ResourceLoader.load_threaded_request(path, "", true)
		if err != OK:
			push_error("StudioLoader: cannot load %s (%d)" % [path, err])


## 0..1 progress of a prefetch (1 when loaded or cached, -1 on failure).
func progress_of(path: String) -> float:
	if ResourceLoader.has_cached(path):
		return 1.0
	var pr := []
	var st := ResourceLoader.load_threaded_get_status(path, pr)
	match st:
		ResourceLoader.THREAD_LOAD_LOADED:
			return 1.0
		ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			return float(pr[0]) if pr.size() > 0 else 0.0
		ResourceLoader.THREAD_LOAD_FAILED:
			return -1.0
	return 0.0


## Wait for a threaded load, feeding the bar between `p0` and `p1`. Returns the resource (null on failure).
func wait_loaded(path: String, p0 := 0.0, p1 := 1.0) -> Resource:
	if ResourceLoader.has_cached(path):
		set_progress(p1)
		return load(path)
	prefetch(path)
	while true:
		var p := progress_of(path)
		if p < 0.0:
			push_error("StudioLoader: loading %s failed" % path)
			return null
		set_progress(lerpf(p0, p1, p))
		if ResourceLoader.load_threaded_get_status(path) == ResourceLoader.THREAD_LOAD_LOADED:
			break
		await get_tree().process_frame
	return ResourceLoader.load_threaded_get(path)


## Show the loading screen, load `path` on a thread, switch to it, then hide (unless opts.hold: the new scene
## calls StudioLoader.end() when it is ready). opts: hold (bool), fade (s).
func load_scene(path: String, scene_tips: Array = [], opts: Dictionary = {}) -> void:
	var hold := bool(opts.get("hold", false))
	await cover(scene_tips, opts)
	var res := await wait_loaded(path, 0.05, 0.35 if hold else 0.9)
	if res is PackedScene:
		get_tree().change_scene_to_packed(res)
	else:
		get_tree().change_scene_to_file(path)
	await get_tree().process_frame
	if not hold:
		set_progress(1.0)
		await end()


## Called by the intro when it is done: straight into the scene when it is loaded (a soft colour flash),
## otherwise through the loading screen.
func handoff(path: String, hold: bool, top: Color, bottom: Color) -> void:
	if not hold and progress_of(path) >= 1.0:
		var res := await wait_loaded(path)
		_show_flat(top, bottom)
		if res is PackedScene:
			get_tree().change_scene_to_packed(res)
		else:
			get_tree().change_scene_to_file(path)
		await get_tree().process_frame
		_fade_out(0.3)
		return
	await cover([], {"fade": 0.3})
	var res2 := await wait_loaded(path, 0.05, 0.35 if hold else 0.9)
	if res2 is PackedScene:
		get_tree().change_scene_to_packed(res2)
	else:
		get_tree().change_scene_to_file(path)
	await get_tree().process_frame
	if not hold:
		set_progress(1.0)
		await end()


## v0.15.4: swap the current scene for `path` through an EMPTY frame, from this autoload (the caller's scene may be
## freed while this runs). Order: leave the signal / tween step that called us -> replace the scene by an empty
## node (the old scene leaves the tree now and is deleted at the next flush) -> wait `frames` frames so every node,
## tween, coroutine and GPU resource of the old scene is really gone -> threaded load (cached: instant) -> switch.
## So the old and the new scene are never resident together, and nothing is freed under a running tween step.
## The loading screen (if up) stays up; the new scene calls end() when it is ready.
var _swapping := false
var swaps := 0                     # tests
var swap_peak := {}                # tests: memory around the last swap (static / video MB, nodes)


func is_swapping() -> bool:
	return _swapping


func swap_scene(path: String, frames := 2) -> void:
	if _swapping:
		return
	_swapping = true
	swaps += 1
	var tree := get_tree()
	await tree.process_frame
	swap_peak = {"before_static": _mb(Performance.MEMORY_STATIC), "before_vid": _mb(Performance.RENDER_VIDEO_MEM_USED),
		"before_nodes": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))}
	prefetch(path)
	var blank := Node.new()
	blank.name = "SceneSwap"
	var ps := PackedScene.new()
	ps.pack(blank)
	blank.free()
	tree.change_scene_to_packed(ps)
	for i in maxi(1, frames):
		await tree.process_frame
	swap_peak["blank_static"] = _mb(Performance.MEMORY_STATIC)
	swap_peak["blank_vid"] = _mb(Performance.RENDER_VIDEO_MEM_USED)
	swap_peak["blank_nodes"] = int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	var res := await wait_loaded(path, 0.1, 0.3)
	_swapping = false
	if res is PackedScene:
		tree.change_scene_to_packed(res)
	else:
		tree.change_scene_to_file(path)


func _mb(m: int) -> float:
	return snappedf(Performance.get_monitor(m) / 1048576.0, 0.1)


# ------------------------------------------------------------------ cover API
## Show the loading screen (or keep the one that is up, swapping in new tips). Await it to be sure it has
## been drawn. opts: fade (s, default 0.15; 0 = instant), progress (start value), title.
func cover(scene_tips: Array = [], opts: Dictionary = {}) -> void:
	await _cover(scene_tips, opts)
	if not _warmed and is_instance_valid(_screen):
		# v0.15.2 fix: once the first loading screen is on screen (boot), render every glyph the tips + title can
		# show, so the MSDF glyph atlas is at its full size from the start instead of growing by 4-8 MB pages
		# (and hitching) on later loads in the middle of a match
		_warmed = true
		# v0.15.4: spread over frames (one tip per frame) - all at once was a ~1 s boot hitch on the S25
		_screen.prewarm_spread(tips + scene_tips + [title_text + ".", String(opts.get("title", ""))])


func _cover(scene_tips: Array, opts: Dictionary) -> void:
	var fade := float(opts.get("fade", 0.15))
	if _fade and _fade.is_valid():
		_fade.kill()
	if not is_instance_valid(_screen):
		_screen = (load(SCREEN) as PackedScene).instantiate()
		_screen.colors = _theme_colors()
		_screen.mascot_pal = StudioDraw.palette(mascot_over)
		add_child(_screen)
	var was_active := _active
	if _screen.flat:
		_screen.modulate.a = 0.0 if not was_active else _screen.modulate.a
	_screen.flat = false
	_screen.title_text = String(opts.get("title", title_text))
	_screen.mouse_filter = Control.MOUSE_FILTER_STOP
	_screen.visible = true
	_local_tips = scene_tips if not scene_tips.is_empty() else tips
	if not was_active:
		_active = true
		_shown_ms = Time.get_ticks_msec()
		_screen.target = float(opts.get("progress", 0.0))
		_screen.progress = _screen.target
		_screen.set_tips(_local_tips)
	elif not scene_tips.is_empty():
		_screen.set_tips(_local_tips)
	if was_active and _screen.modulate.a >= 0.999:
		await get_tree().process_frame
		return
	if fade <= 0.0:
		_screen.modulate.a = 1.0
		await get_tree().process_frame
		covered.emit()
		return
	if not was_active and not _screen.flat:
		_screen.modulate.a = 0.0
	var tw := create_tween()
	_fade = tw
	tw.tween_property(_screen, "modulate:a", 1.0, maxf(0.01, fade * (1.0 - _screen.modulate.a)))
	await tw.finished
	covered.emit()


## Report progress (0..1, never goes backwards while covering).
func set_progress(p: float) -> void:
	if is_instance_valid(_screen) and _active:
		_screen.target = maxf(_screen.target, clampf(p, 0.0, 1.0))


## set_progress + let one frame draw. Returns at once (no frame) when the loading screen is not up, so code
## paths without a loading screen keep their exact timing.
func step(p: float) -> void:
	if not _active:
		return
	set_progress(p)
	await get_tree().process_frame


## Hide the loading screen. hold = true waits out min_display first (so it never just flashes).
## Returns when the fade-out STARTS (await it, then open your scene: the two overlap).
func end(hold := true, fade := 0.25) -> void:
	if not _active:
		return
	set_progress(1.0)
	if hold:
		# wall clock, frame by frame (a SceneTreeTimer can fire up to one long frame early)
		while _active and shown_for() < min_display:
			await get_tree().process_frame
		if not _active:
			return
	_fade_out(fade)
	ended.emit()


func _fade_out(fade: float) -> void:
	_active = false
	if not is_instance_valid(_screen):
		return
	_screen.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if _fade and _fade.is_valid():
		_fade.kill()
	var tw := create_tween()
	_fade = tw
	tw.tween_property(_screen, "modulate:a", 0.0, maxf(0.01, fade))
	tw.tween_callback(func() -> void:
		if not _active and is_instance_valid(_screen):
			_screen.visible = false
			_screen.flat = false)


func _show_flat(top: Color, bottom: Color) -> void:
	if not is_instance_valid(_screen):
		_screen = (load(SCREEN) as PackedScene).instantiate()
		_screen.colors = _theme_colors()
		_screen.mascot_pal = StudioDraw.palette(mascot_over)
		add_child(_screen)
	if _fade and _fade.is_valid():
		_fade.kill()
	_screen.flat = true
	_screen.flat_top = top
	_screen.flat_bottom = bottom
	_screen.visible = true
	_screen.modulate.a = 1.0
	_screen.mouse_filter = Control.MOUSE_FILTER_STOP


func _theme_colors() -> Dictionary:
	var c := {
		"bg_top": StudioBrand.col("bg_top"), "bg_bottom": StudioBrand.col("bg_bottom"),
		"bar": StudioBrand.col("sparkle"), "bar_bg": Color(1, 1, 1, 0.6), "bar_outline": StudioBrand.col("outline"),
		"title": StudioBrand.col("outline"), "tip": StudioBrand.col("outline"), "bokeh": Color(1, 1, 1, 0.12),
	}
	for k in colors:
		c[k] = colors[k]
	return c


func _process(_d: float) -> void:
	# watchdog: a loading screen nobody ended never traps the player
	if _active and shown_for() > max_cover:
		push_warning("StudioLoader: covered for %.0f s without end() - hiding it" % shown_for())
		_fade_out(0.25)
