#!/usr/bin/env bash
# Start the dashboard + worker on http://localhost:8787 (127.0.0.1 only).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -d .venv ] || { echo "Run ./setup.sh first"; exit 1; }
. .venv/bin/activate
if [ "${1:-}" = "doctor" ]; then exec python -m studio doctor; fi
if [ "${1:-}" = "demo" ]; then shift; exec python -m studio demo "$@"; fi
if [ "${1:-}" = "--awake" ]; then
  # keep the Mac from idle-sleeping while the studio runs (lid-close still sleeps; work resumes on wake)
  exec caffeinate -ims python -m studio
fi
exec python -m studio
