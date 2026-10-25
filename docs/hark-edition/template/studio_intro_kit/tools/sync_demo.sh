#!/bin/bash
# copy the addon + tools into the demo project (Godot does not follow symlinked addon folders reliably)
K=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$K/demo/addons" "$K/demo/tools"
rm -rf "$K/demo/addons/studio_intro"; cp -r "$K/addons/studio_intro" "$K/demo/addons/studio_intro"; find "$K/demo/addons/studio_intro" -name "*.uid" -delete
cp "$K/addons/studio_intro/fonts/Fredoka-Bold.ttf.import" "$K/demo/addons/studio_intro/fonts/" 2>/dev/null || true
cp "$K/tools/render.gd" "$K/tools/render.tscn" "$K/demo/tools/"
# re-import so the copied (param-only) .import files are complete again
G=${GODOT:-/workspace/work/godot47/Godot_v4.7.2-stable_linux.arm64}
timeout 300 "$G" --headless --path "$K/demo" --import > "$K/work/import_sync.log" 2>&1 || true
