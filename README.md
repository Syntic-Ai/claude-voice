# claude-voice

**Hands-free, always-listening voice mode for [Claude Code](https://docs.claude.com/en/docs/claude-code).**
Talk to Claude from across the room and never touch the keyboard: no push-to-talk, no Space bar, no Enter.
Say **"go go"** (or your own word) to send, answer Claude's permission prompts and questions out loud,
and Claude answers out loud too.

> Unofficial community tool. Not affiliated with or endorsed by Anthropic.

```
LISTEN → you speak → "…go go" (or 10 s of quiet) → TRANSCRIBE (local) → TYPE → SUBMIT
      → Claude works (anything you say meanwhile is queued) → "Allow this command?" → you: "yes"
      → Claude speaks its answer → LISTEN
```

Claude Code's built-in `/voice` is push-to-talk (hold Space) or tap-to-toggle. `claude-voice` runs the real
`claude` inside a pseudo-terminal and adds a continuous loop around it. Plain `claude` and its `/voice` keep
working exactly as before.

## Install (macOS)

Requirements: [Claude Code](https://docs.claude.com/en/docs/claude-code), Python 3.10–3.13 (or [uv](https://docs.astral.sh/uv/)).

```sh
git clone https://github.com/Syntic-Ai/claude-voice.git ~/claude-voice
~/claude-voice/install.sh
claude-voice
```

The first run downloads the speech model (~500 MB) and macOS asks for microphone access for your terminal app.
All speech recognition runs **locally** (faster-whisper) — no audio leaves your machine.

## Use it

Run `claude-voice` instead of `claude`. All arguments pass through (`claude-voice --continue`, `claude-voice --model opus`, …).

### Sending

End what you say with a **send word**: *"Check the rooftop playground again, **go go**."* It's sent about 2 seconds
after you stop. Defaults: **go go**, **finish**, **do it**, **send it**. Or just go quiet for 10 seconds.

| `submitMode` | Sends when… | Good for |
|---|---|---|
| `both` (default) | you say a send word, **or** after 10 s of quiet | most people |
| `word` | **only** a send word. Pauses never send; everything is collected into one message | long, thoughtful dictation |
| `silence` | only after `silenceMs` of quiet | when you don't want to say a word |

### Everything by voice

| | Say |
|---|---|
| Send now | "…**go go**" / "…**finish**" / "…**do it**" / "…**send it**" (or your own) |
| Answer a permission prompt | "**yes**" · "**always**" (don't ask again) · "**no**" · "**no, use pnpm instead**" (rejects and sends the rest) |
| Answer Claude's question | the option's name (**"green"**), or "**option two**" / "**the second one**" · "**skip**" |
| Stop Claude mid-task (Esc) | "**stop**" / "**interrupt**" |
| Drop what's queued/drafted | "**scratch that**" |
| Pause listening | "**voice off**": sleeps until you say "**voice on**" / "**wake up**" (nothing else gets through) |
| Mute / unmute Claude's voice | "**stop talking**" / "**talk to me**" |
| Change your send word | "**set send word to** banana" / "**add send word** banana" |

Answers are only matched while a dialog is actually open, and only turn into key presses. Speech is never typed into a dialog.

### Keys and commands (optional)

| | Key | Type in Claude (`!` runs it instantly, no tokens) |
|---|---|---|
| Mic fully off / on | F8 | `! voice off` · `! voice on` |
| Spoken replies off / on | F9 | `! voice mute` · `! voice unmute` |
| Set send words | | `! voice send-words "go go" finish` |
| Submit mode | | `! voice submit word` · `silence` · `both` |
| Silence before sending | | `! voice silence 10` (seconds) |
| Names to spell right | | `! voice vocab Syntic "Camila Live" Kubernetes` |
| Show settings / state | | `! voice settings` · `! voice status` |

Settings apply immediately, with no restart. `claude-voice --voice-off` starts muted.
The status line shows `🎙 listening` / `🔴 recording` / `✍️ transcribing` / `💤 asleep` / `⏸ voice off`,
drafts (`📝 12 words …`), queued messages, and `🔈`/`🔇`.

## Safety

- **Never submits while you're speaking.** Voice-activity detection plus an energy gate; a message ends only after
  `silenceMs` of silence (default 10 s, so thinking pauses don't cut you off). Coughs, clicks and short noises are ignored.
- **Only types when Claude is ready.** Claude Code hooks report `idle` / `busy` / `waiting`. Speech while Claude works is
  queued and sent when it finishes. Nothing is ever typed into permission prompts, questions, or startup dialogs.
- **No echo.** The mic is muted while Claude's reply is being spoken, so it never hears itself.
- **Keyboard still works.** Typing pauses voice injection for a moment so you never collide.
- **Everything is scoped.** Hooks and status line are no-ops outside `claude-voice` sessions.

⚠️ Always-on means anything said in the room (TV, calls, other people) gets sent. Say "voice off" when needed,
or raise `vadAggressiveness`.

## Configure

Use the `voice` commands above, or edit `config.json` next to `claude_voice.py` (only the keys you change; defaults shown):

```json
{
  "submitMode": "both",
  "sendPhrases": ["go go", "finish", "do it", "send it"],
  "silenceMs": 10000,
  "vocabulary": [],
  "model": "small.en",
  "vadAggressiveness": 2,
  "whileBusy": "queue",
  "speakReplies": true,
  "sounds": true,
  "toggleKey": "f8",
  "speakToggleKey": "f9",
  "inputDevice": null
}
```

- `sendPhrases` — pick words you won't naturally end a sentence with. The send word is removed from the message.
- `vocabulary` — names Whisper would otherwise mishear (without it, "Syntic and SynteraX" came out as "Cintiq and Cintarax").
- `silenceMs` — quiet time before sending (1000–2000 feels conversational; 10000 suits dictating from across the room).
- `model` — `tiny.en` / `base.en` (faster) … `medium.en` (more accurate). Other languages: `small` + `"language": "de"` etc.
- `vadAggressiveness` — 0–3; 3 = strictest (noisy rooms).
- `whileBusy` — `"queue"` or `"ignore"` speech while Claude is working.
- Spoken voice: macOS `say` by default. Set `CLAUDE_VOICE_TTS` to any command that takes text as its last argument.

See `DEFAULTS` in `claude_voice.py` for every option.

## How it works

| Piece | File |
|---|---|
| PTY wrapper, mic capture, VAD/end-of-speech, Whisper, injection | `claude_voice.py` |
| State hooks (SessionStart/Stop → idle, UserPromptSubmit → busy, PermissionRequest → waiting-permission, AskUserQuestion → waiting-question + its options) | `hook.sh` |
| Reads the reply's `🔊` line aloud (Claude is asked to end replies with one) | `speak.py` |
| Voice state in the status line | `statusline.sh` |
| `voice` control command | `voice` |
| Adds/removes hooks in `~/.claude/settings.json` (backs it up first) | `install_hooks.py` |

## Tests

```sh
.venv/bin/python tests/test_pipeline.py   # synthesized speech + noise → VAD → Whisper
.venv/bin/python tests/test_commands.py   # queueing, voice commands, controls
.venv/bin/python tests/test_voice_features.py  # send words, word mode, sleep/wake, interrupt, dialog answers, vocabulary
.venv/bin/python tests/test_e2e.py        # real claude, spoken input, zero keypresses (uses a little usage)
.venv/bin/python tests/test_e2e_dialogs.py  # real claude: "go go", permission "yes", question "green", all by voice
```

## Uninstall

```sh
~/claude-voice/uninstall.sh && rm -rf ~/claude-voice
```

## License

MIT
