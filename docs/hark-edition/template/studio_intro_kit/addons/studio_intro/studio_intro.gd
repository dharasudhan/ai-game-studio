class_name StudioIntro
extends Control
## Studio intro (~2.8 s): the mascot drops in, squashes, hops into the wordmark as its letter, wiggles; the
## letters pop in one by one with overshoot; a sparkle; then the logo fades and the game takes over
## (through StudioLoader, which shows the loading screen if the next scene is not ready yet).
## Everything is drawn with vector calls (no textures). Brand (name, colours, font, jingle) = brand.json.
##
## Use it as the main scene (set studio_intro/next_scene in Project Settings), call
## StudioIntro.play_then("res://game.tscn") from code, or instance it as an overlay and wait for `finished`.

signal finished

## Scene to open after the intro. Empty = the project setting studio_intro/next_scene; if that is empty too the
## intro just emits `finished` and frees itself (overlay use).
@export_file("*.tscn") var next_scene := ""
## Taps are ignored before this (s).
@export var skip_after := 0.5
## Keep the loading screen up after the scene change until the game calls StudioLoader.end()
## (for games that build their world in _ready). -1 = project setting studio_intro/hold_loader.
@export var hold_loader := -1
@export var play_sound := true

# ---- timeline (s). tools/make_jingle.py uses the same numbers: keep them in sync.
const T_DROP := 0.12      # mascot starts falling
const T_LAND1 := 0.55     # first touch-down (big squash)
const T_HOP := 0.62       # rebound starts
const T_LAND2 := 0.92     # lands in its slot
const T_LETTER0 := 0.80   # first letter pops
const LETTER_GAP := 0.075
const POP_DUR := 0.32
const T_CHEER := 1.62     # happy hop
const T_CHEER_LAND := 1.9
const T_SPARK := 1.70
const T_FADE := 2.35
const T_END := 2.8
const SKIP_FADE := 0.25

var t := 0.0
var _fade_at := T_FADE
var _fade_len := T_END - T_FADE
var _ended := false
var _paused := false
var _player: AudioStreamPlayer
var _pal: Dictionary
var _font: Font
var _word := ""
var _slot := -1
var _next := ""
var _hold := false


## One-line API: play the intro, then open `path` (through the loading screen when it is not loaded yet).
static func play_then(path: String, hold := false) -> void:
	var tree := Engine.get_main_loop() as SceneTree
	tree.set_meta("studio_intro_next", path)
	tree.set_meta("studio_intro_hold", hold)
	tree.change_scene_to_file("res://addons/studio_intro/studio_intro.tscn")


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	process_mode = Node.PROCESS_MODE_ALWAYS
	_pal = StudioDraw.palette()
	_font = StudioBrand.font()
	_word = StudioBrand.wordmark()
	_slot = StudioBrand.mascot_slot()
	var tree := get_tree()
	_next = next_scene
	if tree.has_meta("studio_intro_next"):
		_next = String(tree.get_meta("studio_intro_next"))
		tree.remove_meta("studio_intro_next")
	if _next == "" and get_parent() == tree.root:
		_next = String(ProjectSettings.get_setting("studio_intro/next_scene", ""))
	_hold = bool(ProjectSettings.get_setting("studio_intro/hold_loader", false)) if hold_loader < 0 else hold_loader == 1
	if tree.has_meta("studio_intro_hold"):
		_hold = bool(tree.get_meta("studio_intro_hold"))
		tree.remove_meta("studio_intro_hold")
	if _next != "" and _has_loader():
		_loader().prefetch(_next)
	if play_sound:
		var js = StudioBrand.data().get("jingle", "")
		if String(js) != "" and ResourceLoader.exists(String(js)):
			_player = AudioStreamPlayer.new()
			_player.stream = load(String(js))
			_player.volume_db = float(StudioBrand.data().get("jingle_volume_db", 0.0))
			var bus := String(StudioBrand.data().get("audio_bus", "Master"))
			_player.bus = bus if AudioServer.get_bus_index(bus) >= 0 else "Master"
			add_child(_player)
			_player.play()
	resized.connect(queue_redraw)


func _has_loader() -> bool:
	return get_tree().root.has_node("StudioLoader")


func _loader() -> Node:
	return get_tree().root.get_node("StudioLoader")


## Jump to time `at` (preview / screenshot tools). Freezes the clock when freeze = true.
func seek(at: float, freeze := true) -> void:
	t = at
	_paused = freeze
	if _player and freeze:
		_player.stop()
	queue_redraw()


func _process(delta: float) -> void:
	if _paused or _ended:
		return
	# clamp: a hitch (or coming back from the background) never skips the whole beat
	t += minf(delta, 1.0 / 20.0)
	queue_redraw()
	if t >= _fade_at + _fade_len:
		_finish()


func _gui_input(e: InputEvent) -> void:
	var tap: bool = (e is InputEventScreenTouch and e.pressed) or (e is InputEventMouseButton and e.pressed)
	if tap:
		skip()
		accept_event()


func _unhandled_key_input(e: InputEvent) -> void:
	if e.is_pressed() and (e.is_action("ui_accept") or e.is_action("ui_cancel")):
		skip()


## Skip to the fade (ignored for the first `skip_after` seconds).
func skip(force := false) -> void:
	if _ended or (t < skip_after and not force) or t >= _fade_at:
		return
	_fade_at = t
	_fade_len = SKIP_FADE
	if _player and _player.playing:
		var tw := create_tween()
		tw.tween_property(_player, "volume_db", -40.0, SKIP_FADE)


func _notification(what: int) -> void:
	# backgrounded during the intro: freeze it (and the jingle); on return just fade out into the game
	if what == NOTIFICATION_APPLICATION_PAUSED or what == NOTIFICATION_APPLICATION_FOCUS_OUT:
		if not _ended and not _paused:
			_paused = true
			if _player:
				_player.stream_paused = true
	elif what == NOTIFICATION_APPLICATION_RESUMED or what == NOTIFICATION_APPLICATION_FOCUS_IN:
		if _paused and not _ended:
			_paused = false
			if _player:
				_player.stop()
			if t < _fade_at:
				_fade_at = t
				_fade_len = SKIP_FADE


func _finish() -> void:
	if _ended:
		return
	_ended = true
	if _next != "" and _has_loader():
		_loader().handoff(_next, _hold, StudioBrand.col("bg_top"), StudioBrand.col("bg_bottom"))
	elif _next != "":
		get_tree().change_scene_to_file(_next)
	finished.emit()
	if _next == "":
		var tw := create_tween()
		tw.tween_property(self, "modulate:a", 0.0, 0.25)
		tw.tween_callback(queue_free)


# ------------------------------------------------------------------ animation math
static func ease_out_back(u: float, s := 2.2) -> float:
	u = clampf(u, 0.0, 1.0) - 1.0
	return 1.0 + u * u * ((s + 1.0) * u + s)


static func _spring(tt: float, t0: float, amp: float, k := 7.5, w := 27.0) -> float:
	if tt < t0:
		return 0.0
	var x := tt - t0
	return -amp * exp(-k * x) * cos(w * x)


## Mascot state at time tt for a fall height `h0` and hop height `h1` (px). Shared with the logo renderer.
static func mascot_state(tt: float, h0: float, h1: float, h2: float, look_x := -0.85) -> Dictionary:
	var lift := 0.0
	var q := 0.0
	var vis := tt >= T_DROP
	if tt < T_LAND1:
		var u := clampf((tt - T_DROP) / (T_LAND1 - T_DROP), 0.0, 1.0)
		lift = h0 * (1.0 - u * u)
		q = 0.24 * u
	elif tt < T_HOP:
		lift = 0.0
	elif tt < T_LAND2:
		var w := (tt - T_HOP) / (T_LAND2 - T_HOP)
		lift = h1 * 4.0 * w * (1.0 - w)
	elif tt >= T_CHEER and tt < T_CHEER_LAND:
		var w2 := (tt - T_CHEER) / (T_CHEER_LAND - T_CHEER)
		lift = h2 * 4.0 * w2 * (1.0 - w2)
	q += _spring(tt, T_LAND1, 0.4) + _spring(tt, T_LAND2, 0.24) + _spring(tt, T_CHEER_LAND, 0.16)
	# anticipation squash before the cheer hop
	if tt > T_CHEER - 0.1 and tt < T_CHEER:
		q -= 0.14 * sin((tt - (T_CHEER - 0.1)) / 0.1 * PI)
	if tt >= T_CHEER and tt < T_CHEER_LAND:
		q += 0.12 * sin((tt - T_CHEER) / (T_CHEER_LAND - T_CHEER) * PI)
	var sy := 1.0 + q
	var sx := 1.0 / pow(maxf(0.3, sy), 0.65)
	var lean := 0.0
	if tt > T_LAND2:
		var x := tt - T_LAND2
		lean = 0.24 * exp(-3.2 * x) * sin(15.0 * x)
	var wob := 0.025
	if tt > T_LAND1:
		wob += 0.08 * exp(-4.0 * (tt - T_LAND1))
	if tt > T_LAND2:
		wob += 0.05 * exp(-4.0 * (tt - T_LAND2))
	var look := Vector2(0, 0.9) if tt < T_LAND1 else Vector2.ZERO
	if tt > T_LETTER0 + 0.05 and tt < 1.38:
		look = Vector2(look_x, 0.15)
	var eye := 1.0
	if tt > 1.44 and tt < 1.56:
		eye = absf((tt - 1.5) / 0.06)
	if tt >= T_CHEER and tt < T_CHEER_LAND + 0.18:
		eye = 0.0
	var mouth := 0.55 if tt < T_LAND1 else maxf(0.0, 1.0 - (tt - T_LAND1) * 2.2)
	if tt >= T_CHEER - 0.02 and tt < T_CHEER_LAND + 0.3:
		mouth = 1.0
	return {"vis": vis, "lift": lift, "sx": sx, "sy": sy, "lean": lean, "wob": wob, "phase": tt * 13.0,
		"look": look, "eye_open": eye, "mouth": mouth, "tuft": clampf(-q * 1.8 + lean * 2.4, -1.0, 1.0)}


# ------------------------------------------------------------------ layout + draw
## Wordmark layout for a box: font size S, baseline, per-letter x centres, the mascot slot.
static func layout(word: String, slot: int, font: Font, box: Rect2) -> Dictionary:
	var ref := 100
	var adv: Array = []
	var total := 0.0
	# an all-caps wordmark gets letter spacing (chunky caps with thick outlines would touch otherwise)
	var caps := word == word.to_upper()
	var track := 0.08 * ref if caps else 0.0
	for i in word.length():
		var a := (0.95 if caps else 0.9) * ref + track if i == slot else font.get_string_size(word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, ref).x * 1.01 + track
		adv.append(a)
		total += a
	var portrait := box.size.y > box.size.x
	var wcap := box.size.x * (0.8 if portrait else 0.56)
	var s := float(ref) * wcap / maxf(1.0, total)
	s = minf(s, box.size.y * (0.2 if portrait else 0.3))
	if slot < 0:
		s = minf(s, box.size.y * 0.16)
	var k := s / float(ref)
	var x := box.get_center().x - total * k * 0.5
	var xs: Array = []
	for a in adv:
		xs.append(x + float(a) * k * 0.5)
		x += float(a) * k
	var block_h := s * (1.15 if slot >= 0 else 2.2)
	var base := box.get_center().y + block_h * 0.5 - s * 0.38
	return {"s": s, "xs": xs, "adv": adv.map(func(a): return float(a) * k), "base": base, "width": total * k}


func _draw() -> void:
	var rect := get_viewport().get_visible_rect()
	rect.position = Vector2.ZERO
	StudioDraw.bg(self, rect, StudioBrand.col("bg_top"), StudioBrand.col("bg_bottom"))
	var box := StudioBrand.safe_rect(get_viewport())
	var a := 1.0
	if t > _fade_at:
		a = clampf(1.0 - (t - _fade_at) / maxf(0.01, _fade_len), 0.0, 1.0)
		a = a * a
	draw_logo(self, t, box, a, _pal, _font, _word, _slot, String(StudioBrand.data().get("subline", "")))


## Draws the whole logo state at time tt into `box` (also used by the logo/preview renderer).
static func draw_logo(ci: CanvasItem, tt: float, box: Rect2, alpha: float, pal: Dictionary, font: Font, word: String, slot: int, sub: String) -> void:
	if alpha <= 0.001:
		return
	var L := layout(word, slot, font, box)
	var s: float = L.s
	var base: float = L.base
	var outline: Color = pal.outline
	var shadow: Color = pal.shadow
	var ol := int(s * 0.15)
	var j := 0
	var last_pop := T_LETTER0
	var far_top := Vector2.ZERO
	var far_d := -1.0
	for i in word.length():
		if i == slot:
			continue
		var t0 := T_LETTER0 + LETTER_GAP * float(j)
		last_pop = t0
		j += 1
		var u := (tt - t0) / POP_DUR
		if u <= 0.0:
			continue
		var sc := ease_out_back(u, 2.6)
		var la := clampf(u * 4.0, 0.0, 1.0) * alpha
		var rot := (1.0 - clampf(u, 0.0, 1.0)) * (0.35 if j % 2 == 0 else -0.35)
		var dy := (1.0 - ease_out_back(u, 1.4)) * s * 0.28
		var cx: float = L.xs[i]
		var aw: float = font.get_string_size(word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s)).x
		var pos := Vector2(cx, base + dy)
		# second sparkle: on the letter furthest from the mascot (its top outer corner)
		var dslot: float = absf(cx - float(L.xs[slot])) if slot >= 0 else float(j)
		if dslot > far_d:
			far_d = dslot
			var side := 1.0 if slot >= 0 and cx > float(L.xs[slot]) else -1.0
			far_top = Vector2(cx + side * aw * 0.4, base - s * 0.72)
		ci.draw_set_transform(pos, rot, Vector2(sc, sc))
		var o := Vector2(-aw * 0.5, 0)
		ci.draw_string_outline(font, o + Vector2(0, s * 0.07), word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s), ol, Color(shadow, shadow.a * la))
		ci.draw_string(font, o + Vector2(0, s * 0.07), word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s), Color(shadow, shadow.a * la))
		ci.draw_string_outline(font, o, word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s), ol, Color(outline, la))
		ci.draw_string(font, o + Vector2(0, -s * 0.022), word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s), Color(pal.letter_hi, la))
		ci.draw_string(font, o + Vector2(0, s * 0.012), word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, int(s), Color(pal.letter, la))
		ci.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	# subline (e.g. GAMES): letter-spaced, rises in after the wordmark
	if sub != "":
		var ss := s * 0.3
		var track := ss * 0.32
		var w := 0.0
		var ws: Array = []
		for ch in sub:
			var cw := font.get_string_size(ch, HORIZONTAL_ALIGNMENT_LEFT, -1, int(ss)).x
			ws.append(cw)
			w += cw + track
		w -= track
		var x := box.get_center().x - w * 0.5
		var sb := base + s * (0.5 if word == word.to_upper() else 0.64)   # caps have no descenders
		var t1 := last_pop + 0.22
		var ssl := int(maxf(2.0, ss * 0.12))
		for k in sub.length():
			var u2 := (tt - (t1 + 0.035 * float(k))) / 0.3
			if u2 > 0.0:
				var a2 := clampf(u2 * 3.0, 0.0, 1.0) * alpha
				var dy2 := (1.0 - ease_out_back(u2, 1.8)) * ss * 0.9
				ci.draw_string_outline(font, Vector2(x, sb + dy2), sub[k], HORIZONTAL_ALIGNMENT_LEFT, -1, int(ss), ssl, Color(1, 1, 1, 0.9 * a2))
				ci.draw_string(font, Vector2(x, sb + dy2), sub[k], HORIZONTAL_ALIGNMENT_LEFT, -1, int(ss), Color(pal.subline, a2))
			x += float(ws[k]) + track
	# mascot
	var r := s * 0.37 if slot >= 0 else s * 0.55
	var foot := Vector2(L.xs[slot], base) if slot >= 0 else Vector2(box.get_center().x, base - s * 0.95)
	var h0 := foot.y - box.position.y + r * 2.6
	var look_x := 0.85 if slot >= 0 and slot * 2 < word.length() else -0.85
	var st := mascot_state(tt, h0, s * 0.62, s * 0.22, look_x)
	if st.vis:
		st["alpha"] = alpha
		StudioDraw.mascot(ci, foot, r, st, pal)
	# sparkles
	var su := (tt - T_SPARK) / 0.55
	if su > 0.0 and su < 1.0:
		var kk := pow(sin(su * PI), 0.8) * alpha
		StudioDraw.sparkle(ci, foot + Vector2(r * 1.0, -r * 2.3 - float(st.lift)), r * 0.85, kk, su * 2.0, pal.sparkle)
		for d in 6:
			var ang := -PI * 0.5 + (float(d) - 2.5) * 0.55
			var dist := r * (1.2 + su * 1.3)
			StudioDraw.fill_ellipse(ci, foot + Vector2(0, -r - float(st.lift)) + Vector2(cos(ang), sin(ang)) * dist, Vector2.ONE * r * 0.07 * (1.0 - su), Color(pal.sparkle, (1.0 - su) * alpha))
	var su2 := (tt - (T_SPARK + 0.12)) / 0.5
	if su2 > 0.0 and su2 < 1.0 and far_top != Vector2.ZERO:
		StudioDraw.sparkle(ci, far_top, r * 0.5, pow(sin(su2 * PI), 0.8) * alpha, -su2 * 1.6, pal.sparkle)
