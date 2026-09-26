#!/bin/sh
# Claude Code hook: records session state for claude-voice. No-op outside claude-voice sessions.
cat >/dev/null
[ -n "$CLAUDE_VOICE_STATE" ] || exit 0
printf '%s' "$1" > "$CLAUDE_VOICE_STATE"
exit 0
