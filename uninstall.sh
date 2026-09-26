#!/bin/sh
# Removes claude-voice hooks and commands. Your other settings are kept (a backup is made first).
DIR=$(cd "$(dirname "$0")" && pwd)
PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" "$DIR/install_hooks.py" --uninstall
for c in claude-voice voice; do
  [ "$(readlink "$HOME/.local/bin/$c")" = "$DIR/$c" ] && rm -f "$HOME/.local/bin/$c"
done
echo "Removed. Delete $DIR to remove everything else."
