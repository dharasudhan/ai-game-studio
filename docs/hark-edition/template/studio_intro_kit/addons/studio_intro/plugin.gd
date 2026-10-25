@tool
extends EditorPlugin
## Enabling the plugin registers the StudioLoader autoload (you can also add it by hand in Project Settings).


func _enable_plugin() -> void:
	add_autoload_singleton("StudioLoader", "res://addons/studio_intro/studio_loader.gd")


func _disable_plugin() -> void:
	remove_autoload_singleton("StudioLoader")
