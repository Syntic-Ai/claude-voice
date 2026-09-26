#!/usr/bin/env python3
"""Claude Code Stop hook: reads the reply's 🔊 line aloud. Active only inside claude-voice sessions.

TTS command: $CLAUDE_VOICE_TTS (text is appended as the last argument), else `say` on macOS,
else `spd-say` / `espeak` on Linux. Muted while <repo>/speak-off exists (`voice mute`, F9, "stop talking").
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def spoken_line(transcript_path: str) -> str:
    text = ""
    with open(transcript_path) as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            for c in row.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c["text"]
    for line in text.splitlines():
        if "🔊" in line:
            return re.sub(r"[*_`>#]", "", line.split("🔊", 1)[1]).strip()[:300]
    return ""


def tts_command() -> list[str] | None:
    if os.environ.get("CLAUDE_VOICE_TTS"):
        return shlex.split(os.environ["CLAUDE_VOICE_TTS"])
    for cmd in ("say", "spd-say", "espeak"):
        if shutil.which(cmd):
            return [cmd]
    return None


def main() -> int:
    data = sys.stdin.read()
    if not os.environ.get("CLAUDE_VOICE_STATE") or os.path.exists(os.path.join(HERE, "speak-off")):
        return 0
    try:
        tp = json.loads(data).get("transcript_path") or ""
        say = spoken_line(tp) if os.path.isfile(tp) else ""
    except (ValueError, OSError):
        return 0
    cmd = tts_command()
    if say and cmd:
        subprocess.Popen([*cmd, say], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)   # detached: never delays the turn
    return 0


if __name__ == "__main__":
    sys.exit(main())
