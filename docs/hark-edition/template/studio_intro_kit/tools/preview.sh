#!/bin/bash
# Render the intro preview (MP4 + GIF + 3 key frames per orientation) into preview/.
# Needs: Godot 4.3+ (GODOT=...), an X display (DISPLAY=:97 or xvfb-run), ffmpeg.
set -euo pipefail
K=$(cd "$(dirname "$0")/.." && pwd)
G=${GODOT:-/workspace/work/godot47/Godot_v4.7.2-stable_linux.arm64}
[ "${NOSYNC:-0}" = 1 ] || "$K/tools/sync_demo.sh"
timeout 300 "$G" --headless --path "$K/demo" --import > "$K/work/import.log" 2>&1 || true
P="$K/preview"; mkdir -p "$P" "$K/work"
for sz in ${SIZES:-1080x2400 2400x1080}; do
  o=$([ $sz = 1080x2400 ] && echo portrait || echo landscape)
  F="$K/work/fr_$sz"; rm -rf "$F"
  MODE=frames FPS=30 SIZE=$sz OUT="$F" timeout 600 "$G" --rendering-driver opengl3 --path "$K/demo" res://tools/render.tscn > "$K/work/render_$sz.log" 2>&1
  grep -q "RENDER: done" "$K/work/render_$sz.log" || { echo "render failed ($sz)"; exit 1; }
  if grep -qE "SCRIPT ERROR|Failed loading resource" "$K/work/render_$sz.log"; then echo "errors in render log ($sz)"; grep -E "SCRIPT ERROR|Failed loading" "$K/work/render_$sz.log" | head; exit 1; fi
  ffmpeg -y -loglevel error -framerate 30 -i "$F/f_%04d.png" -i "$K/addons/studio_intro/audio/jingle.ogg" -c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -b:a 160k -shortest -movflags +faststart "$P/intro_${o}_${sz}.mp4"
  W=$([ $o = portrait ] && echo 360 || echo 640)
  ffmpeg -y -loglevel error -framerate 30 -i "$F/f_%04d.png" -vf "fps=20,scale=$W:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$P/intro_${o}.gif"
  cp "$F/f_0017.png" "$P/key1_squash_${o}.png"
  cp "$F/f_0030.png" "$P/key2_letterpop_${o}.png"
  cp "$F/f_0052.png" "$P/key3_sparkle_${o}.png"
done
echo "preview: $(ls "$P" | wc -l) files in $P"
