# claude-voice

**Hands-free, always-listening voice mode for [Claude Code](https://docs.claude.com/en/docs/claude-code).**
Talk to Claude from across the room — no push-to-talk, no Space bar, no Enter. Stop talking and it sends.
Claude answers out loud.

> Unofficial community tool. Not affiliated with or endorsed by Anthropic.

```
LISTEN → you speak → RECORD → you go quiet (10 s) → TRANSCRIBE (local) → TYPE → SUBMIT
      → Claude works (anything you say meanwhile is queued) → Claude speaks its answer → LISTEN
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

| | Say | Key | Type in Claude |
|---|---|---|---|
| Stop listening (mic fully closed) | "voice off" | F8 | `! voice off` |
| Start listening | — | F8 | `! voice on` |
| Mute Claude's spoken replies | "stop talking" | F9 | `! voice mute` |
| Unmute | "talk to me" | F9 | `! voice unmute` |
| Drop queued messages | "scratch that" | — | — |
| Show state | — | — | `! voice status` |

The `!` prefix runs the command instantly without using a model turn. `claude-voice --voice-off` starts muted.
The status line shows `🎙 listening` / `🔴 recording` / `✍️ transcribing` / `⏸ voice off` and `🔈`/`🔇`.

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

Create `config.json` next to `claude_voice.py` with any overrides (defaults shown):

```json
{
  "silenceMs": 10000,
  "model": "small.en",
  "vadAggressiveness": 2,
  "minSpeechMs": 400,
  "whileBusy": "queue",
  "speakReplies": true,
  "sounds": true,
  "toggleKey": "f8",
  "speakToggleKey": "f9",
  "inputDevice": null
}
```

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
| State hooks (SessionStart/Stop → idle, UserPromptSubmit → busy, PermissionRequest/AskUserQuestion → waiting) | `hook.sh` |
| Reads the reply's `🔊` line aloud (Claude is asked to end replies with one) | `speak.py` |
| Voice state in the status line | `statusline.sh` |
| `voice` control command | `voice` |
| Adds/removes hooks in `~/.claude/settings.json` (backs it up first) | `install_hooks.py` |

## Tests

```sh
.venv/bin/python tests/test_pipeline.py   # synthesized speech + noise → VAD → Whisper
.venv/bin/python tests/test_commands.py   # queueing, voice commands, controls
.venv/bin/python tests/test_e2e.py        # real claude, spoken input, zero keypresses (uses a little usage)
```

## Uninstall

```sh
~/claude-voice/uninstall.sh && rm -rf ~/claude-voice
```

## License

MIT
