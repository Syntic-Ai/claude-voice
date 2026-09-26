#!/bin/sh
# Claude Code hook: records session state for claude-voice. No-op outside claude-voice sessions.
# Question dialogs also save the hook payload (the options) so they can be answered by voice.
[ -n "$CLAUDE_VOICE_STATE" ] || { cat >/dev/null; exit 0; }
state="$1"
payload=$(cat)
# AskUserQuestion also raises PermissionRequest — keep it a question, not a yes/no prompt.
if [ "$state" = waiting-permission ] && printf '%s' "$payload" | grep -q '"tool_name": *"AskUserQuestion"'; then
  state=waiting-question
fi
[ "$state" = waiting-question ] && printf '%s' "$payload" > "$CLAUDE_VOICE_STATE.payload"
printf '%s' "$state" > "$CLAUDE_VOICE_STATE"
exit 0
