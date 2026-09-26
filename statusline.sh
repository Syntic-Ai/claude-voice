#!/bin/sh
# Claude Code statusLine: shows the voice state inside claude-voice sessions, nothing elsewhere.
cat >/dev/null
[ -n "$CLAUDE_VOICE_STATUS" ] && [ -f "$CLAUDE_VOICE_STATUS" ] && cat "$CLAUDE_VOICE_STATUS"
exit 0
