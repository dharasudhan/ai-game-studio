class_name StudioBrand
extends RefCounted
## Studio brand config for the intro + loading kit. Everything that names or colours the studio lives in ONE file,
## res://addons/studio_intro/brand.json (or the path in the project setting studio_intro/brand_path).
## Godot 4.3 .. 4.7 compatible (no typed dictionaries, no 4.4+ API).

const DEFAULT_PATH := "res://addons/studio_intro/brand.json"

const DEFAULTS := {
	"studio_name": "Studio",
	"wordmark": "Studio",
	"subline": "GAMES",
	"mascot_slot": "auto",
	"colors": {
		"bg_top": "#FFF7E8", "bg_bottom": "#FFD9B8", "letter": "#3A8DFF", "letter_hi": "#A9D4FF",
		"outline": "#1F2559", "shadow": "#1F255938", "subline": "#1F2559", "mascot": "#FF5DA2",
		"mascot_shade": "#D93A85", "mascot_hi": "#FFC4DE", "cheek": "#FF2E7E66", "eye": "#1F2559",
		"sparkle": "#FFD23F",
	},
	"font": "res://addons/studio_intro/fonts/Fredoka-Bold.ttf",
	"font_weight": 700,
	"jingle": "res://addons/studio_intro/audio/jingle.ogg",
	"jingle_volume_db": -3.0,
	"audio_bus": "Master",
	"logo_texture": "",
	"mark_texture": "",
}

static var _cache: Dictionary = {}
static var _fonts: Dictionary = {}


## The merged brand (defaults <- brand.json). Colours stay strings here; use col().
static func data() -> Dictionary:
	if not _cache.is_empty():
		return _cache
	var path := String(ProjectSettings.get_setting("studio_intro/brand_path", DEFAULT_PATH))
	var d: Dictionary = DEFAULTS.duplicate(true)
	if FileAccess.file_exists(path):
		var j = JSON.parse_string(FileAccess.get_file_as_string(path))
		if j is Dictionary:
			for k in j:
				if k == "colors" and j[k] is Dictionary:
					for ck in j[k]:
						d.colors[ck] = j[k][ck]
				else:
					d[k] = j[k]
		else:
			push_error("StudioBrand: %s is not valid JSON - using defaults" % path)
	else:
		push_error("StudioBrand: %s missing (add 'addons/studio_intro/*.json' to the export include filter) - using defaults" % path)
	_cache = d
	return _cache


## Forget the cached brand (tools / tests that edit brand.json at runtime).
static func reload() -> void:
	_cache = {}


static func col(key: String, fallback := Color.WHITE) -> Color:
	var c = data().colors.get(key, "")
	if c is String and c != "":
		return Color.html(c)
	return fallback


static func wordmark() -> String:
	return String(data().get("wordmark", "Studio"))


## Index of the wordmark letter the mascot stands in for, or -1 (mascot sits above the wordmark).
## "auto" = the last o / O / 0 in the wordmark.
static func mascot_slot() -> int:
	var s = data().get("mascot_slot", "auto")
	var w := wordmark()
	if s is float or s is int:
		var i := int(s)
		return i if i >= 0 and i < w.length() else -1
	if String(s) == "above":
		return -1
	for i in range(w.length() - 1, -1, -1):
		if w[i] in ["o", "O", "0"]:
			return i
	return -1


## The brand font as a FontVariation at the brand weight (variable Fredoka: wght axis).
static func font(weight := -1) -> Font:
	var wgt := int(data().get("font_weight", 700)) if weight < 0 else weight
	if _fonts.has(wgt):
		return _fonts[wgt]
	var path := String(data().get("font", ""))
	var base: Font = null
	if path != "" and ResourceLoader.exists(path):
		base = load(path)
	if base == null:
		base = ThemeDB.fallback_font
	var fv := FontVariation.new()
	fv.base_font = base
	var ts := TextServerManager.get_primary_interface()
	if ts != null:
		fv.variation_opentype = {ts.name_to_tag("wght"): wgt}
	_fonts[wgt] = fv
	return fv


static func texture(key: String) -> Texture2D:
	var p := String(data().get(key, ""))
	if p != "" and ResourceLoader.exists(p):
		return load(p)
	return null


## Safe-area rectangle in the root viewport's coordinates (canvas_items stretch aware). Desktop: the whole view.
static func safe_rect(vp: Viewport) -> Rect2:
	var full := vp.get_visible_rect()
	if not (OS.has_feature("mobile") or OS.has_feature("web_android") or OS.has_feature("web_ios")):
		return full
	var sa := DisplayServer.get_display_safe_area()
	var win := DisplayServer.window_get_size()
	if sa.size.x <= 0 or sa.size.y <= 0 or win.x <= 0 or win.y <= 0:
		return full
	var k := full.size / Vector2(win)
	var r := Rect2(Vector2(sa.position) * k + full.position, Vector2(sa.size) * k)
	r = r.intersection(full)
	return r if r.size.x > full.size.x * 0.5 and r.size.y > full.size.y * 0.5 else full
