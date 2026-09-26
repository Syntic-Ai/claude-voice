#!/usr/bin/env python3
"""Add (or with --uninstall, remove) claude-voice hooks in ~/.claude/settings.json.

Every hook is a no-op outside claude-voice sessions (they check $CLAUDE_VOICE_STATE).
A timestamped backup of settings.json is written before any change.
"""
import json
import os
import shlex
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
HOOK = shlex.quote(os.path.join(HERE, "hook.sh"))
SPEAK = f'{shlex.quote(os.path.join(HERE, ".venv", "bin", "python"))} {shlex.quote(os.path.join(HERE, "speak.py"))}'
STATUS = shlex.quote(os.path.join(HERE, "statusline.sh"))

ENTRIES = [
    ("SessionStart", None, f"{HOOK} idle"),
    ("Stop", None, f"{HOOK} idle"),
    ("UserPromptSubmit", None, f"{HOOK} busy"),
    ("PermissionRequest", None, f"{HOOK} waiting-permission"),
    ("PreToolUse", "AskUserQuestion", f"{HOOK} waiting-question"),
    ("PostToolUse", "AskUserQuestion", f"{HOOK} busy"),
]


def ours(cmd: str) -> bool:
    return HERE in cmd.replace("'", "")


def main() -> int:
    uninstall = "--uninstall" in sys.argv
    speak = "--no-speak" not in sys.argv
    settings = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as f:
            settings = json.load(f)
        backup = f"{SETTINGS}.bak-claude-voice-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
        print(f"backup: {backup}")
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    hooks = settings.setdefault("hooks", {})

    # always strip our old entries first, so re-running install is idempotent
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            g = dict(g, hooks=[h for h in g.get("hooks", []) if not ours(h.get("command", ""))])
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if ours((settings.get("statusLine") or {}).get("command", "")):
        del settings["statusLine"]

    if not uninstall:
        entries = ENTRIES + ([("Stop", None, SPEAK)] if speak else [])
        for event, matcher, cmd in entries:
            group = {"hooks": [{"type": "command", "command": cmd}]}
            if matcher:
                group = {"matcher": matcher, **group}
            hooks.setdefault(event, []).append(group)
        if settings.get("statusLine"):
            print("note: you already have a statusLine, left unchanged. To show voice state, have it print "
                  f"the contents of $CLAUDE_VOICE_STATUS (see {os.path.join(HERE, 'statusline.sh')}).")
        else:
            settings["statusLine"] = {"type": "command", "command": STATUS}
    if not hooks:
        settings.pop("hooks", None)

    with open(SETTINGS, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(("removed claude-voice hooks from " if uninstall else "installed claude-voice hooks in ") + SETTINGS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
