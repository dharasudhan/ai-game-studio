class_name StudioDraw
extends RefCounted
## Vector drawing for the studio mascot (a round jelly blob with big eyes and a little curl on top), the sparkle
## and the background gradient. Pure CanvasItem draw calls: no textures, crisp at any resolution, a few hundred
## vertices per frame. Used by the intro, the loading screen and the logo renderer.

const N := 56


static func _ellipse(c: Vector2, r: Vector2, n := 28, rot := 0.0) -> PackedVector2Array:
	var p := PackedVector2Array()
	p.resize(n)
	for i in n:
		var a := TAU * float(i) / float(n)
		p[i] = c + Vector2(cos(a) * r.x, sin(a) * r.y).rotated(rot)
	return p


static func fill_ellipse(ci: CanvasItem, c: Vector2, r: Vector2, col: Color, rot := 0.0) -> void:
	if r.x < 0.3 or r.y < 0.3:
		return
	ci.draw_colored_polygon(_ellipse(c, r, 28, rot), col)


## Full-screen vertical gradient (two triangles, vertex colours).
static func bg(ci: CanvasItem, rect: Rect2, top: Color, bottom: Color, alpha := 1.0) -> void:
	var t := Color(top, top.a * alpha)
	var b := Color(bottom, bottom.a * alpha)
	var pts := PackedVector2Array([rect.position, Vector2(rect.end.x, rect.position.y), rect.end, Vector2(rect.position.x, rect.end.y)])
	ci.draw_polygon(pts, PackedColorArray([t, t, b, b]))


## The mascot. `foot` = point on the ground under its centre; r = radius at rest.
## st keys (all optional): sx, sy (squash/stretch), lean (rad-ish shear), wob (jelly wobble amount), phase,
## eye_open (0..1), look (Vector2 -1..1), mouth (0 smile .. 1 open), tuft (curl lag, -1..1), alpha,
## shadow (0..1 shadow strength), lift (height above the ground in px, for the shadow).
static func mascot(ci: CanvasItem, foot: Vector2, r: float, st: Dictionary, pal: Dictionary) -> void:
	var sx := float(st.get("sx", 1.0))
	var sy := float(st.get("sy", 1.0))
	var lean := float(st.get("lean", 0.0))
	var wob := float(st.get("wob", 0.0))
	var ph := float(st.get("phase", 0.0))
	var a := float(st.get("alpha", 1.0))
	var lift := float(st.get("lift", 0.0))
	var body: Color = pal.get("mascot", Color("#FF5DA2"))
	var shade: Color = pal.get("mascot_shade", body.darkened(0.2))
	var hi: Color = pal.get("mascot_hi", body.lightened(0.5))
	var outline: Color = pal.get("outline", Color("#1F2559"))
	var eye: Color = pal.get("eye", outline)
	var cheek: Color = pal.get("cheek", Color(1, 0.2, 0.5, 0.4))
	# ground shadow: smaller + fainter the higher it is
	var sh := float(st.get("shadow", 1.0))
	if sh > 0.0:
		var k := clampf(1.0 - lift / (r * 6.0), 0.25, 1.0)
		fill_ellipse(ci, foot + Vector2(0, r * 0.02), Vector2(r * 0.95 * sx * k, r * 0.2 * k), Color(outline, 0.22 * sh * a * k))
	var base := foot - Vector2(0, lift)
	var c := base - Vector2(0, r * sy)            # pivot at the bottom: squash keeps the feet on the ground
	var pts := PackedVector2Array()
	var cols := PackedColorArray()
	pts.resize(N)
	cols.resize(N)
	for i in N:
		var ang := TAU * float(i) / float(N)
		var ca := cos(ang)
		var sa := sin(ang)
		var rr := r * (1.0 + wob * (0.55 * sin(3.0 * ang + ph) + 0.45 * sin(2.0 * ang - ph * 1.3)))
		# a touch bottom-heavy (jelly sits on its belly)
		var yy := sa * rr * sy * (1.0 + 0.06 * maxf(sa, 0.0))
		var xx := ca * rr * sx * (1.0 + 0.05 * maxf(sa, 0.0))
		xx += lean * (-(yy - r * sy)) * 0.5       # shear around the feet
		pts[i] = c + Vector2(xx, yy)
		var v := clampf((sa + 1.0) * 0.5, 0.0, 1.0)  # 0 top .. 1 bottom
		cols[i] = Color(hi.lerp(body, smoothstep(0.0, 0.55, v)).lerp(shade, smoothstep(0.55, 1.0, v)), a)
	# outline first (thick, under the fill so the fill edge stays clean)
	var ow := maxf(1.5, r * 0.085)
	var closed := pts.duplicate()
	closed.append(pts[0])
	closed.append(pts[1])
	ci.draw_polyline(closed, Color(outline, a), ow * 2.0, true)
	# curl on top (tuft): a little teardrop that lags behind the motion
	var top := c + Vector2(lean * r * sy * 0.5, -r * sy * 0.98)
	var tuft := float(st.get("tuft", 0.0))
	var tip := top + Vector2(r * (0.16 + 0.35 * tuft), -r * (0.42 - 0.06 * absf(tuft)) * clampf(sy, 0.6, 1.4))
	_tuft(ci, top, tip, r, Color(outline, a), ow, cols[42], a)
	ci.draw_polygon(pts, cols)
	# inner jelly glow
	var inner := PackedVector2Array()
	inner.resize(N)
	for i in N:
		inner[i] = c + (pts[i] - c) * 0.78 + Vector2(0, -r * 0.06 * sy)
	ci.draw_colored_polygon(inner, Color(hi, 0.22 * a))
	# face, scaled with the body
	var fs := Vector2(sx, sy)
	var fc := c + Vector2(lean * r * sy * 0.25, r * 0.08 * sy)
	var look: Vector2 = st.get("look", Vector2.ZERO)
	var eo := clampf(float(st.get("eye_open", 1.0)), 0.0, 1.0)
	for sgn in [-1.0, 1.0]:
		var ec := fc + Vector2(sgn * r * 0.33, -r * 0.12) * fs
		var er := Vector2(r * 0.2, r * 0.25) * fs
		if eo > 0.12:
			fill_ellipse(ci, ec, er + Vector2(ow * 0.6, ow * 0.6 * eo), Color(outline, a))
			fill_ellipse(ci, ec, Vector2(er.x, er.y * eo), Color(1, 1, 1, a))
			var pc := ec + Vector2(look.x * er.x * 0.38, look.y * er.y * 0.3 * eo + er.y * 0.08 * eo)
			fill_ellipse(ci, pc, Vector2(er.x * 0.7, er.y * 0.7 * eo), Color(eye, a))
			fill_ellipse(ci, pc + Vector2(-er.x * 0.22, -er.y * 0.26 * eo), Vector2(er.x * 0.24, er.y * 0.22 * eo), Color(1, 1, 1, a))
			fill_ellipse(ci, pc + Vector2(er.x * 0.2, er.y * 0.22 * eo), Vector2(er.x * 0.1, er.y * 0.09 * eo), Color(1, 1, 1, 0.8 * a))
		else:
			# closed / happy eyes: an arch
			ci.draw_arc(ec + Vector2(0, er.y * 0.2), er.x * 0.85, PI * 1.12, PI * 1.88, 12, Color(eye, a), ow * 1.3, true)
		fill_ellipse(ci, ec + Vector2(sgn * r * 0.1, r * 0.33) * fs, Vector2(r * 0.15, r * 0.085) * fs, Color(cheek, cheek.a * a))
	# mouth
	var m := clampf(float(st.get("mouth", 0.0)), 0.0, 1.0)
	var mc := fc + Vector2(0, r * 0.24) * fs
	if m < 0.15:
		ci.draw_arc(mc + Vector2(0, -r * 0.06 * sy), r * 0.13 * sx, PI * 0.15, PI * 0.85, 12, Color(eye, a), ow * 1.1, true)
	else:
		var mw := r * (0.13 + 0.05 * m) * sx
		var mh := r * (0.06 + 0.13 * m) * sy
		var mp := PackedVector2Array()
		for i in 15:
			var t := PI * float(i) / 14.0
			mp.append(mc + Vector2(cos(t) * mw, sin(t) * mh))
		ci.draw_colored_polygon(mp, Color(eye, a))
		fill_ellipse(ci, mc + Vector2(0, mh * 0.62), Vector2(mw * 0.55, mh * 0.3), Color(1.0, 0.45, 0.55, a))
	# shine
	fill_ellipse(ci, c + Vector2(-r * 0.45 * sx, -r * 0.5 * sy), Vector2(r * 0.2 * sx, r * 0.12 * sy), Color(1, 1, 1, 0.75 * a), -0.6)
	fill_ellipse(ci, c + Vector2(-r * 0.22 * sx, -r * 0.7 * sy), Vector2(r * 0.055, r * 0.05), Color(1, 1, 1, 0.8 * a))


static func _tuft(ci: CanvasItem, base: Vector2, tip: Vector2, r: float, ol: Color, ow: float, col: Color, a: float) -> void:
	# a curved teardrop from the head to `tip`
	var d := tip - base
	var nrm := Vector2(-d.y, d.x).normalized()
	var pts := PackedVector2Array()
	var steps := 14
	var w := r * 0.17
	for i in steps + 1:
		var t := float(i) / float(steps)
		var p := base + d * t + nrm * sin(t * PI) * r * 0.12
		pts.append(p + nrm * w * (1.0 - t) * (0.6 + 0.4 * t))
	for i in range(steps, -1, -1):
		var t := float(i) / float(steps)
		var p := base + d * t + nrm * sin(t * PI) * r * 0.12
		pts.append(p - nrm * w * (1.0 - t) * (0.6 + 0.4 * t))
	var ring := pts.duplicate()
	ring.append(pts[0])
	ci.draw_polyline(ring, ol, ow * 1.6, true)
	fill_ellipse(ci, tip, Vector2(ow * 1.6, ow * 1.6), ol)
	ci.draw_colored_polygon(pts, Color(col, a))
	fill_ellipse(ci, tip, Vector2(ow * 0.85, ow * 0.85), Color(col, a))


## 4-point sparkle star (k = 0..1 size), with a soft glow.
static func sparkle(ci: CanvasItem, c: Vector2, size: float, k: float, rot: float, col: Color) -> void:
	if k <= 0.01:
		return
	var s := size * k
	fill_ellipse(ci, c, Vector2(s * 0.55, s * 0.55), Color(col, 0.22 * k))
	var pts := PackedVector2Array()
	for i in 8:
		var ang := rot + TAU * float(i) / 8.0
		var rr := s if i % 2 == 0 else s * 0.22
		pts.append(c + Vector2(cos(ang), sin(ang)) * rr)
	ci.draw_colored_polygon(pts, Color(col, minf(1.0, k * 1.5)))
	fill_ellipse(ci, c, Vector2(s * 0.12, s * 0.12), Color(1, 1, 1, minf(1.0, k * 1.5)))


## Palette dictionary from the brand (colours as Color), optionally overridden by a theme dictionary.
static func palette(over: Dictionary = {}) -> Dictionary:
	var p := {}
	for k in StudioBrand.data().colors:
		p[k] = StudioBrand.col(k)
	for k in over:
		var v = over[k]
		p[k] = Color.html(v) if v is String else v
	return p
