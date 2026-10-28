#!/usr/bin/env bash
# One-time setup for macOS (Apple Silicon). Safe to re-run. Installs nothing without telling you.
#   ./setup.sh                 core setup (python venv, deps, checks)
#   ./setup.sh --with-agy      also install Antigravity CLI (Google's official installer)
#   ./setup.sh --with-gemini-cli  also npm-install the legacy Gemini CLI (API-key use only, see README)
#   ./setup.sh --with-claude   also install Claude Code (Anthropic's native installer)
#   ./setup.sh --with-codex    also install OpenAI Codex CLI (Homebrew cask)
#   ./setup.sh --with-ollama   also install Ollama (Homebrew) for local models
# After setup, the dashboard opens a guided setup wizard (models per agent, keys, identity): http://localhost:8787/#setup
# Install commands per docs/SETUP_MODELS.md (official docs checked 2026-10-28).
set -euo pipefail
cd "$(dirname "$0")"
WITH_AGY=0; WITH_GEMINI=0; WITH_CLAUDE=0; WITH_CODEX=0; WITH_OLLAMA=0
for a in "$@"; do case "$a" in --with-agy) WITH_AGY=1;; --with-gemini-cli) WITH_GEMINI=1;; --with-claude) WITH_CLAUDE=1;;
  --with-codex) WITH_CODEX=1;; --with-ollama) WITH_OLLAMA=1;; esac; done
say(){ printf "\n\033[1m==> %s\033[0m\n" "$*"; }
ok(){ printf "  [ok] %s\n" "$*"; }
warn(){ printf "  [!!] %s\n" "$*"; }

[ "$(uname -s)" = "Darwin" ] || warn "This script targets macOS; continuing anyway."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

say "Homebrew"
if ! command -v brew >/dev/null; then
  warn "Homebrew missing. Install it first:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi
ok "$(brew --version | head -1)"

say "Core tools (python 3.11+, git, node)"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v $c >/dev/null && $c -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then PY=$c; break; fi
done
if [ -z "$PY" ]; then brew install python@3.12; PY=python3.12; fi
ok "python: $($PY --version)"
command -v git >/dev/null || brew install git; ok "git: $(git --version)"
command -v node >/dev/null || brew install node; ok "node: $(node --version)"

say "Godot 4.7.x"
GODOT=""
for c in godot godot4 /Applications/Godot.app/Contents/MacOS/Godot /Applications/Godot_v4.7*.app/Contents/MacOS/Godot; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then GODOT="$c"; break; fi
done
if [ -n "$GODOT" ]; then ok "godot: $GODOT ($("$GODOT" --version 2>/dev/null | head -1))"
  case "$("$GODOT" --version 2>/dev/null)" in 4.7*) ;; *) warn "Not 4.7.x. New games are generated for Godot 4.7 (4.3 hit Android bugs).";; esac
else
  warn "Godot not found. Download 4.7.2 stable for macOS: https://godotengine.org/download/macos/"
  warn "Move Godot.app to /Applications and open it once (Gatekeeper), or set godot_bin in Settings."
fi

say "AI engine: Antigravity CLI (agy)"
if command -v agy >/dev/null; then ok "agy: $(command -v agy) ($(agy --version 2>/dev/null | head -1))"
elif [ $WITH_AGY = 1 ]; then
  echo "  Running Google's installer: curl -fsSL https://antigravity.google/cli/install.sh | bash"
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  command -v agy >/dev/null && ok "agy installed" || warn "agy not on PATH yet; open a new terminal"
else
  warn "agy missing. Re-run with --with-agy, or: curl -fsSL https://antigravity.google/cli/install.sh | bash"
fi
if [ $WITH_CLAUDE = 1 ]; then
  say "Claude Code CLI"
  if command -v claude >/dev/null; then ok "claude: $(claude --version 2>/dev/null | head -1)"
  else echo "  Running Anthropic's installer: curl -fsSL https://claude.ai/install.sh | bash"; curl -fsSL https://claude.ai/install.sh | bash; fi
  echo "  Then run \`claude\` once and sign in (Claude Pro/Max login, or an API key)."
fi
if [ $WITH_CODEX = 1 ]; then
  say "OpenAI Codex CLI"
  command -v codex >/dev/null && ok "codex: $(codex --version 2>/dev/null | head -1)" || brew install --cask codex
  echo "  Then run \`codex\` once and choose Sign in with ChatGPT (or use an API key)."
fi
if [ $WITH_OLLAMA = 1 ]; then
  say "Ollama (local models)"
  command -v ollama >/dev/null && ok "ollama present" || brew install ollama
  echo "  Start it (open the app or run \`ollama serve\`), then: ollama pull qwen2.5-coder:7b"
fi
if [ $WITH_GEMINI = 1 ]; then
  say "Legacy Gemini CLI (npm @google/gemini-cli)"
  npm install -g @google/gemini-cli && ok "gemini: $(gemini --version 2>/dev/null)"
fi

say "Python virtualenv + dependencies"
[ -d .venv ] || $PY -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
ok "venv ready ($(python --version))"

[ -f .env ] || { cp .env.example .env; ok "created .env (edit it for GODOT/ANDROID paths, optional API key)"; }
chmod +x run.sh
mkdir -p data/logs

say "Optional extras"
command -v ollama >/dev/null && ok "ollama present (local models: ollama pull qwen2.5-coder:7b)" || echo "  ollama (optional, local models): ./setup.sh --with-ollama"
if [ -n "${ANDROID_HOME:-}" ]; then ok "ANDROID_HOME=$ANDROID_HOME"; else echo "  Android export: see README step 5 (JDK 17 + Android SDK)"; fi

say "Self-check"
python -m studio doctor || true
cat <<'MSG'

Next:
  1. If you haven't yet: run `agy` once in a terminal and choose Sign in with Google
     (use the Google account that has your Google AI Pro subscription).
  2. ./run.sh            then open http://localhost:8787 : the setup wizard walks you through
     models per agent, API keys (saved to the macOS Keychain), connection tests and studio identity.
     Full provider guide: docs/SETUP_MODELS.md (PDF: dist/AI-Game-Studio-Model-Setup-Guide.pdf)
  3. Optional: ./run.sh --awake   (keeps the Mac awake while it works)
MSG
