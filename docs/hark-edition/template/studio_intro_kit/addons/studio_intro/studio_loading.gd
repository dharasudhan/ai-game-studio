extends Control
## Loading screen view (driven by the StudioLoader autoload). Vector-drawn: themed gradient, soft bokeh,
## the bouncing studio mascot, a rounded progress bar, a title and a rotating tip line.

var colors := {}          # theme colours (Color)
var mascot_pal := {}      # palette for the mascot (brand + theme overrides)
var tips: Array = []
var title_text := "Loading"
var flat := false         # true = just the gradient (scene hand-off flash)
var flat_top := Color.WHITE
var flat_bottom := Color.WHITE
var progress := 0.0       # displayed (eased) progress 0..1
var target := 0.0
var clock := 0.0
var _tip_i := 0
var _tip_t := 0.0
var _tip: Label
var _font: Font


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	process_mode = Node.PROCESS_MODE_ALWAYS
	_font = StudioBrand.font(650)
	_tip = Label.new()
	_tip.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_tip.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_tip.vertical_alignment = VERTICAL_ALIGNMENT_TOP
	_tip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_tip.add_theme_font_override("font", StudioBrand.font(550))
	add_child(_tip)
	if not tips.is_empty():
		_tip_i = randi() % tips.size()
	_apply_tip()
	resized.connect(_relayout)
	_relayout()


## Rasterise every glyph of `lines` in both loader fonts (tip + title) now. MSDF glyphs are large (msdf_size 96),
## so letting each new tip add glyphs lazily grows the atlas in 4-8 MB steps in the middle of a match.
## The lines are shaped first, so ligatures (fl, fi) are the exact glyphs the Label will draw.
func prewarm(lines: Array) -> void:
	var ts := TextServerManager.get_primary_interface()
	if ts == null or _tip == null:
		return
	var fs := maxi(16, int(_tip.get_theme_font_size("font_size")))
	for f in [_font, _tip.get_theme_font("font")]:
		if f == null:
			continue
		for l in lines:
			var s := String(l)
			if s == "":
				continue
			var tl := TextLine.new()
			tl.add_string(s, f, fs)
			for g in ts.shaped_text_get_glyphs(tl.get_rid()):
				var frid: RID = g.get("font_rid", RID())
				if frid.is_valid():
					ts.font_render_glyph(frid, Vector2i(fs, 0), int(g.get("index", 0)))


func set_tips(t: Array) -> void:
	tips = t
	_tip_i = randi() % tips.size() if not tips.is_empty() else 0
	_tip_t = 0.0
	_apply_tip()


func _apply_tip() -> void:
	if _tip == null:
		return
	_tip.visible = not tips.is_empty() and not flat
	if not tips.is_empty():
		_tip.text = String(tips[_tip_i % tips.size()])
	_tip.add_theme_color_override("font_color", colors.get("tip", Color("#1F2559")))


func _relayout() -> void:
	if _tip == null:
		return
	var box := StudioBrand.safe_rect(get_viewport())
	var m := minf(box.size.x, box.size.y)
	var fs := int(clampf(m * 0.045, 14.0, 64.0))
	_tip.add_theme_font_size_override("font_size", fs)
	var w := minf(box.size.x * 0.84, m * 1.5)
	_tip.size = Vector2(w, fs * 4.2)
	_tip.position = Vector2(box.get_center().x - w * 0.5, _bar_y(box) + m * 0.085)


func _bar_y(box: Rect2) -> float:
	var portrait := box.size.y > box.size.x
	return box.position.y + box.size.y * (0.6 if portrait else 0.66)


func _process(delta: float) -> void:
	var dt := minf(delta, 0.1)
	clock += dt
	progress = minf(target, progress + maxf(0.0, target - progress) * minf(1.0, dt * 9.0) + dt * 0.02)
	if tips.size() > 1:
		_tip_t += dt
		if _tip_t > 3.6:
			_tip_t = 0.0
			_tip_i += 1
			_apply_tip()
	queue_redraw()


func _draw() -> void:
	var rect := get_viewport().get_visible_rect()
	rect.position = Vector2.ZERO
	if flat:
		StudioDraw.bg(self, rect, flat_top, flat_bottom)
		return
	StudioDraw.bg(self, rect, colors.get("bg_top", Color("#FFF7E8")), colors.get("bg_bottom", Color("#FFD9B8")))
	var box := StudioBrand.safe_rect(get_viewport())
	var m := minf(box.size.x, box.size.y)
	# soft drifting bokeh
	var bk: Color = colors.get("bokeh", Color(1, 1, 1, 0.1))
	for i in 7:
		var fx := fposmod(0.13 + 0.17 * float(i) + clock * 0.012 * (1.0 + 0.3 * float(i % 3)), 1.2) - 0.1
		var fy := 0.15 + 0.7 * fposmod(0.37 * float(i * i) + 0.11, 1.0) + 0.02 * sin(clock * 0.7 + float(i))
		StudioDraw.fill_ellipse(self, Vector2(rect.size.x * fx, rect.size.y * fy), Vector2.ONE * m * (0.06 + 0.035 * float(i % 4)), bk)
	# mascot hopping above the bar
	var bar_y := _bar_y(box)
	var r := m * 0.105
	var foot := Vector2(box.get_center().x, bar_y - m * 0.11)
	var P := 0.64
	var tau := fposmod(clock, P)
	var air := 0.46
	var lift := 0.0
	var q := 0.0
	if tau < air:
		var w := tau / air
		lift = r * 1.1 * 4.0 * w * (1.0 - w)
		q = 0.1 * sin(w * PI)
	else:
		var g := tau - air
		q = -0.28 * exp(-11.0 * g) * cos(26.0 * g) * (1.0 - g / (P - air))
	var sy := 1.0 + q
	var blink := fposmod(clock, 2.7) > 2.58
	var st := {"lift": lift, "sy": sy, "sx": 1.0 / pow(maxf(0.3, sy), 0.65), "wob": 0.03 + 0.03 * absf(q),
		"phase": clock * 9.0, "look": Vector2(0.0, 0.55), "eye_open": 0.0 if blink else 1.0, "mouth": 0.0,
		"tuft": clampf(-q * 2.0 + sin(clock * 6.0) * 0.15, -1.0, 1.0)}
	StudioDraw.mascot(self, foot, r, st, mascot_pal)
	# title
	var ts := int(clampf(m * 0.06, 16.0, 90.0))
	var dots := int(fposmod(clock * 2.5, 4.0))
	var title := title_text + ".".repeat(dots)
	var tw := _font.get_string_size(title_text + "...", HORIZONTAL_ALIGNMENT_LEFT, -1, ts).x
	var tp := Vector2(box.get_center().x - tw * 0.5, bar_y - m * 0.025)
	draw_string_outline(_font, tp, title, HORIZONTAL_ALIGNMENT_LEFT, -1, ts, int(ts * 0.18), colors.get("title_outline", Color(1, 1, 1, 0.85)))
	draw_string(_font, tp, title, HORIZONTAL_ALIGNMENT_LEFT, -1, ts, colors.get("title", Color("#1F2559")))
	# progress bar
	var bw := minf(box.size.x * 0.72, m * 1.25)
	var bh := maxf(10.0, m * 0.045)
	var br := Rect2(box.get_center().x - bw * 0.5, bar_y + m * 0.02, bw, bh)
	var ow := maxf(2.0, bh * 0.16)
	var olc: Color = colors.get("bar_outline", Color("#1F2559"))
	_round(br.grow(ow), olc)
	# the track is drawn opaque (a translucent track over the outline would turn grey): blend it over the page colour
	var tb: Color = colors.get("bar_bg", Color(1, 1, 1, 0.6))
	var page: Color = (colors.get("bg_top", Color.WHITE) as Color).lerp(colors.get("bg_bottom", Color.WHITE), (br.position.y) / maxf(1.0, rect.size.y))
	_round(br, Color(page.lerp(Color(tb, 1.0), tb.a), 1.0))
	var fw := maxf(bh, bw * clampf(progress, 0.0, 1.0))
	var fr := Rect2(br.position, Vector2(fw, bh))
	var fc: Color = colors.get("bar", Color("#FFD23F"))
	_round(fr, fc)
	_round(Rect2(fr.position + Vector2(bh * 0.25, bh * 0.16), Vector2(maxf(0.0, fw - bh * 0.5), bh * 0.26)), Color(1, 1, 1, 0.45))


func _round(r: Rect2, c: Color) -> void:
	var sb := StyleBoxFlat.new()
	sb.bg_color = c
	sb.set_corner_radius_all(int(r.size.y * 0.5))
	sb.corner_detail = 8
	sb.anti_aliasing = true
	draw_style_box(sb, r)
