#!/bin/sh
# claude-voice installer: local venv + dependencies, commands on PATH, Claude Code hooks.
# Usage: ./install.sh [--no-speak]     (--no-speak: don't install the read-replies-aloud hook)
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
BIN="$HOME/.local/bin"

command -v claude >/dev/null || { echo "Claude Code (claude) not found on PATH. Install it first."; exit 1; }
[ "$(uname)" = Darwin ] || echo "warning: claude-voice is built and tested on macOS; other systems are untested."

echo "→ creating Python environment"
if command -v uv >/dev/null; then
  uv venv --python 3.12 -q "$DIR/.venv"
  uv pip install --python "$DIR/.venv/bin/python" -q -r "$DIR/requirements.txt"
else
  PY=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
  "$PY" -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,14), "need Python 3.10-3.13 (or install uv)"'
  "$PY" -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi

echo "→ linking commands into $BIN"
mkdir -p "$BIN"
chmod +x "$DIR/claude-voice" "$DIR/voice" "$DIR/hook.sh" "$DIR/statusline.sh"
ln -sf "$DIR/claude-voice" "$BIN/claude-voice"
ln -sf "$DIR/voice" "$BIN/voice"

echo "→ adding Claude Code hooks"
"$DIR/.venv/bin/python" "$DIR/install_hooks.py" "$@"

case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: add $BIN to your PATH";; esac
echo
echo "Done. Run:  claude-voice      (first run downloads the speech model, ~500 MB)"
echo "macOS will ask for microphone access for your terminal app; allow it."
