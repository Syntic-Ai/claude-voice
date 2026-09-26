#!/usr/bin/env python3
"""claude-voice — hands-free continuous dictation for Claude Code.

Runs the real `claude` binary inside a pseudo-terminal and adds a loop:

    LISTEN -> SPEECH DETECTED -> RECORD -> END-OF-SPEECH (VAD + silence)
    -> TRANSCRIBE (local Whisper) -> INSERT -> AUTO-SUBMIT -> WAIT UNTIL SAFE -> LISTEN

"Safe" comes from Claude Code hooks (hook.sh) that write the session state
(idle / busy / waiting) to the file named by $CLAUDE_VOICE_STATE. Plain `claude`
sessions don't set that variable, so the hooks do nothing there.

Controls:  F8 toggles listening on/off (the mic is fully closed when off).
           Say "voice off" / "stop listening" to turn it off hands-free.
           Say "cancel that" / "scratch that" to drop queued utterances.
"""
from __future__ import annotations

import json
import os
import pty
import queue
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import fcntl
import struct
from collections import deque

import numpy as np

HOME = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HOME, "config.json")
RUN_DIR = os.path.join(HOME, "run")
SPEAK_OFF = os.path.join(HOME, "speak-off")   # presence mutes the TTS Stop hook (all sessions)


def speaking() -> bool:
    return not os.path.exists(SPEAK_OFF)


def set_speaking(on: bool):
    if on:
        try:
            os.remove(SPEAK_OFF)
        except FileNotFoundError:
            pass
    else:
        open(SPEAK_OFF, "w").close()
        subprocess.run(["pkill", "-x", "say"], capture_output=True)          # cut off anything mid-sentence
        subprocess.run(["pkill", "-f", "afplay.*claude-tts"], capture_output=True)

DEFAULTS = {
    "continuousVoice": True,       # start listening immediately
    "silenceMs": 10000,            # end-of-speech: submit after this much silence
    "minSpeechMs": 400,            # voiced audio needed to count as an utterance (filters coughs/clicks)
    "startWindowMs": 300,          # speech starts when this window is mostly voiced...
    "startRatio": 0.7,             # ...by this fraction
    "preRollMs": 600,              # audio kept from before speech start
    "maxUtteranceSec": 90,
    "vadAggressiveness": 2,        # 0-3, higher = stricter about what counts as speech
    "minRms": 0.002,               # energy gate on top of the VAD (0-1 float scale)
    "model": "small.en",           # faster-whisper model: tiny.en, base.en, small.en, medium.en
    "language": "en",
    "whileBusy": "queue",          # "queue": hold utterances until Claude is idle; "ignore": drop them
    "submitDelayMs": 500,          # wait after Claude becomes idle before typing
    "typingGraceMs": 2000,         # don't inject while you're typing on the keyboard
    "quietIdleMs": 6000,           # fallback: "busy" with no screen output this long => idle (e.g. after Esc)
    "pauseDuringAudio": True,      # mute the mic while these processes play (TTS echo guard)
    "audioProcesses": ["afplay", "say", "spd-say", "espeak"],
    "sounds": True,                # short chime on accept / on / off
    "toggleKey": "f8",
    "speakToggleKey": "f9",
    "muteSpeechPhrases": ["stop talking", "be quiet", "mute voice", "speech off"],
    "unmuteSpeechPhrases": ["start talking", "talk to me", "speech on"],
    "stopPhrases": ["voice off", "stop listening", "voice mode off"],
    "cancelPhrases": ["cancel that", "scratch that", "never mind that"],
    "inputDevice": None,           # sounddevice device name/index, None = system default
    "claudeCommand": "claude",
    "speakReplies": True,          # ask Claude to end replies with a 🔊 line (read aloud by the TTS Stop hook)
    "speakPrompt": ("The user is talking to you hands-free by voice and cannot see the screen. "
                    "End every reply with one final line starting with 🔊 followed by one or two short, "
                    "natural spoken sentences summarizing what you did or found, or asking your question. "
                    "Plain words only: no markdown, code, file paths, or symbols in that line."),
}

KEYS = {"f5": b"\x1b[15~", "f6": b"\x1b[17~", "f7": b"\x1b[18~", "f8": b"\x1b[19~",
        "f9": b"\x1b[20~", "f10": b"\x1b[21~", "f12": b"\x1b[24~"}

HALLUCINATIONS = {
    "", "you", "thank you", "thank you.", "thanks for watching", "thanks for watching!",
    "thank you for watching", "bye", "bye.", "okay.", ".", "...", "so", "uh", "um",
    "[music]", "[blank_audio]", "(silence)", "[silence]", "(music)", "[ silence ]",
}

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def load_config(path: str = os.environ.get("CLAUDE_VOICE_CONFIG", CONFIG_PATH)) -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


# ─── End-of-speech segmentation ──────────────────────────────────────────────

class Segmenter:
    """Feeds 30 ms int16 frames; returns a finished utterance (int16 bytes) or None."""

    def __init__(self, cfg: dict, is_speech=None):
        import webrtcvad
        self.cfg = cfg
        self.vad = webrtcvad.Vad(int(cfg["vadAggressiveness"]))
        self._is_speech = is_speech or (lambda fr: self.vad.is_speech(fr, SAMPLE_RATE))
        self.start_n = max(1, cfg["startWindowMs"] // FRAME_MS)
        self.pre = deque(maxlen=max(self.start_n, cfg["preRollMs"] // FRAME_MS))
        self.window = deque(maxlen=self.start_n)
        self.reset()

    def reset(self):
        self.in_speech = False
        self.frames: list[bytes] = []
        self.voiced_ms = 0
        self.silence_ms = 0
        self.pre.clear()
        self.window.clear()

    def voiced(self, frame: bytes) -> bool:
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        return rms >= self.cfg["minRms"] and self._is_speech(frame)

    def feed(self, frame: bytes) -> bytes | None:
        v = self.voiced(frame)
        if not self.in_speech:
            self.pre.append(frame)
            self.window.append(v)
            if len(self.window) == self.start_n and sum(self.window) >= self.cfg["startRatio"] * self.start_n:
                self.in_speech = True
                self.frames = list(self.pre)
                self.voiced_ms = sum(self.window) * FRAME_MS
                self.silence_ms = 0
            return None
        self.frames.append(frame)
        if v:
            self.voiced_ms += FRAME_MS
            self.silence_ms = 0
        else:
            self.silence_ms += FRAME_MS
        too_long = len(self.frames) * FRAME_MS >= self.cfg["maxUtteranceSec"] * 1000
        if self.silence_ms >= self.cfg["silenceMs"] or too_long:
            keep_tail = 200 // FRAME_MS
            drop = max(0, self.silence_ms // FRAME_MS - keep_tail)
            frames = self.frames[: len(self.frames) - drop] if drop else self.frames
            enough = self.voiced_ms >= self.cfg["minSpeechMs"]
            self.reset()
            return b"".join(frames) if enough else None
        return None

    @property
    def recording(self) -> bool:
        return self.in_speech


# ─── Transcription ───────────────────────────────────────────────────────────

class Transcriber:
    def __init__(self, cfg: dict):
        from faster_whisper import WhisperModel
        self.cfg = cfg
        self.model = WhisperModel(cfg["model"], device="cpu", compute_type="int8")

    def transcribe(self, pcm16: bytes) -> str:
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=self.cfg["language"], beam_size=5,
            condition_on_previous_text=False, vad_filter=False,
        )
        parts = [s.text for s in segments
                 if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return clean_transcript(" ".join(parts))


def clean_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[/!#\s]+", "", text)  # never trigger slash-commands / bash / memory modes
    if text.lower().strip(" .!?,") in {h.strip(" .!?,") for h in HALLUCINATIONS}:
        return ""
    return text


def normalize(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


# ─── Session state (fed by hooks) ────────────────────────────────────────────

class SessionState:
    """idle | busy | waiting, from the hook-written file plus local overrides."""

    def __init__(self, path: str, cfg: dict):
        self.path = path
        self.cfg = cfg
        self.value = "waiting"
        self.since = time.monotonic()
        self._mtime = 0.0
        self.write("waiting")   # SessionStart hook flips this to idle once Claude is past startup dialogs

    def write(self, value: str):
        with open(self.path, "w") as f:
            f.write(value)
        self._set(value)
        self._mtime = os.stat(self.path).st_mtime

    def _set(self, value: str):
        if value != self.value:
            self.value = value
            self.since = time.monotonic()

    def poll(self, last_output: float, last_key: float) -> str:
        try:
            m = os.stat(self.path).st_mtime
            if m != self._mtime:
                self._mtime = m
                with open(self.path) as f:
                    self._set(f.read().strip() or "idle")
        except FileNotFoundError:
            pass
        now = time.monotonic()
        # A key pressed in a permission dialog means the user handled it.
        if self.value == "waiting" and last_key > self.since:
            self._set("busy")
        # Esc-interrupts don't fire Stop; the spinner stops redrawing, so go idle on quiet.
        quiet = self.cfg["quietIdleMs"] / 1000
        if self.value == "busy" and now - self.since > quiet and now - last_output > quiet:
            self.write("idle")
        return self.value


# ─── Microphone listener ─────────────────────────────────────────────────────

class Listener:
    def __init__(self, cfg: dict, on_event):
        self.cfg = cfg
        self.on_event = on_event          # callback(kind, payload)
        self.enabled = False
        self.frames: queue.Queue = queue.Queue()
        self.utterances: queue.Queue = queue.Queue()
        self.stream = None
        self.segmenter = Segmenter(cfg)
        self.transcriber = None
        self._audio_playing = False
        self._lock = threading.Lock()
        threading.Thread(target=self._load_model, daemon=True).start()
        threading.Thread(target=self._segment_loop, daemon=True).start()
        threading.Thread(target=self._transcribe_loop, daemon=True).start()
        if cfg["pauseDuringAudio"]:
            threading.Thread(target=self._audio_watch, daemon=True).start()

    def _load_model(self):
        self.on_event("status", "loading model")
        try:
            self.transcriber = Transcriber(self.cfg)
            self.on_event("status", "listening" if self.enabled else "off")
        except Exception as e:  # noqa: BLE001
            self.on_event("error", f"model load failed: {e}")

    def _callback(self, indata, frames, t, status):
        self.frames.put(bytes(indata))

    def start(self):
        import sounddevice as sd
        test_wav = os.environ.get("CLAUDE_VOICE_TEST_AUDIO")
        if test_wav:  # test hook: play a 16 kHz mono WAV in real time instead of the mic
            import wave

            def feed():
                with wave.open(test_wav) as w:
                    while (chunk := w.readframes(FRAME_SAMPLES)):
                        self.frames.put(chunk)
                        time.sleep(FRAME_MS / 1000)
            self.enabled = True
            threading.Thread(target=feed, daemon=True).start()
            self.on_event("status", "listening")
            return
        with self._lock:
            if self.stream is None:
                self.segmenter.reset()
                self.stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    blocksize=FRAME_SAMPLES, device=self.cfg["inputDevice"],
                    callback=self._callback)
                self.stream.start()
            self.enabled = True
        self.on_event("status", "listening")

    def stop(self):
        with self._lock:
            self.enabled = False
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None
            self.segmenter.reset()
            while not self.frames.empty():
                self.frames.get_nowait()
        self.on_event("status", "off")

    def _audio_watch(self):
        names = self.cfg["audioProcesses"]
        while True:
            playing = any(subprocess.run(["pgrep", "-x", n], capture_output=True).returncode == 0
                          for n in names)
            if playing != self._audio_playing:
                self._audio_playing = playing
                if playing:
                    self.segmenter.reset()   # discard anything captured with speaker bleed
                else:
                    time.sleep(0.3)          # let the room tail die out
            time.sleep(0.25)

    def _segment_loop(self):
        was_recording = False
        while True:
            frame = self.frames.get()
            if not self.enabled or self._audio_playing:
                if was_recording:
                    was_recording = False
                    self.on_event("status", "listening")
                continue
            buf = frame
            while len(buf) >= FRAME_SAMPLES * 2:
                fr, buf = buf[: FRAME_SAMPLES * 2], buf[FRAME_SAMPLES * 2:]
                utt = self.segmenter.feed(fr)
                if self.segmenter.recording and not was_recording:
                    was_recording = True
                    self.on_event("status", "recording")
                if utt is not None or (was_recording and not self.segmenter.recording):
                    was_recording = False
                    self.on_event("status", "listening")
                if utt is not None:
                    self.utterances.put(utt)

    def _transcribe_loop(self):
        while True:
            utt = self.utterances.get()
            while self.transcriber is None:
                time.sleep(0.2)
            self.on_event("status", "transcribing")
            try:
                text = self.transcriber.transcribe(utt)
            except Exception as e:  # noqa: BLE001
                self.on_event("error", f"transcription failed: {e}")
                continue
            self.on_event("status", "listening" if self.enabled else "off")
            if text:
                self.on_event("text", text)


# ─── PTY wrapper around claude ───────────────────────────────────────────────

class VoiceSession:
    def __init__(self, cfg: dict, claude_args: list[str]):
        self.cfg = cfg
        self.args = claude_args
        os.makedirs(RUN_DIR, exist_ok=True)
        pid = os.getpid()
        self.state_path = os.path.join(RUN_DIR, f"{pid}.state")
        self.status_path = os.path.join(RUN_DIR, f"{pid}.status")
        self.state = SessionState(self.state_path, cfg)
        self.pending: deque[str] = deque()
        self.events: queue.Queue = queue.Queue()
        self.toggle_seq = KEYS[cfg["toggleKey"].lower()]
        self.speak_seq = KEYS[cfg["speakToggleKey"].lower()]
        self.ctl_path = os.path.join(RUN_DIR, f"{pid}.ctl")
        open(self.ctl_path, "w").close()
        self._ctl_mtime = os.stat(self.ctl_path).st_mtime
        self.last_output = time.monotonic()
        self.last_key = 0.0
        self.enter_at: float | None = None
        self.status = "starting"
        self.listener: Listener | None = None

    # events arrive from listener threads; handled on the main loop
    def on_event(self, kind: str, payload: str):
        self.events.put((kind, payload))

    def set_status(self, s: str):
        self.status = s
        q = f" · {len(self.pending)} queued" if self.pending else ""
        icon = {"listening": "🎙 listening", "recording": "🔴 recording", "transcribing": "✍️  transcribing",
                "off": "⏸  voice off", "loading model": "⏳ loading speech model"}.get(s, s)
        spk = "🔈 speaking" if speaking() else "🔇 muted"
        keys = f'{self.cfg["toggleKey"].upper()} mic · {self.cfg["speakToggleKey"].upper()} speech'
        try:
            with open(self.status_path, "w") as f:
                f.write(f"{icon}{q} · {spk}  ({keys})")
        except OSError:
            pass

    def chime(self, name: str):
        if self.cfg["sounds"]:
            subprocess.Popen(["afplay", f"/System/Library/Sounds/{name}.aiff"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def set_listening(self, on: bool):
        if self.listener is None or self.listener.enabled == on:
            return
        self.toggle()

    def toggle_speaking(self, on: bool | None = None):
        set_speaking(not speaking() if on is None else on)
        self.chime("Pop" if speaking() else "Bottle")
        self.set_status(self.status)

    def poll_ctl(self):
        """Commands from `voice ...` (run via Claude's ! prefix) arrive through the ctl file."""
        try:
            m = os.stat(self.ctl_path).st_mtime
        except FileNotFoundError:
            return
        if m == self._ctl_mtime:
            return
        self._ctl_mtime = m
        with open(self.ctl_path) as f:
            cmds = f.read().split()
        open(self.ctl_path, "w").close()
        self._ctl_mtime = os.stat(self.ctl_path).st_mtime
        for c in cmds:
            if c in ("listen-on", "listen-off"):
                self.set_listening(c == "listen-on")
            elif c == "listen-toggle":
                self.toggle()
            elif c == "speak-changed":
                self.set_status(self.status)

    def toggle(self):
        if self.listener is None:
            return
        if self.listener.enabled:
            self.listener.stop()
            self.chime("Bottle")
        else:
            self.listener.start()
            self.chime("Pop")

    def handle_text(self, text: str):
        n = normalize(text)
        if n in self.cfg["muteSpeechPhrases"] or n in self.cfg["unmuteSpeechPhrases"]:
            self.toggle_speaking(n in self.cfg["unmuteSpeechPhrases"])
            return
        if n in self.cfg["stopPhrases"]:
            self.listener.stop()
            self.chime("Bottle")
            return
        if n in self.cfg["cancelPhrases"]:
            self.pending.clear()
            self.chime("Basso")
            self.set_status(self.status)
            return
        busy = self.state.value != "idle" or self.pending
        if busy and self.cfg["whileBusy"] == "ignore":
            return
        self.pending.append(text)
        self.chime("Tink")
        self.set_status(self.status)

    def try_inject(self, fd: int):
        now = time.monotonic()
        if self.enter_at is not None:
            if now >= self.enter_at:
                os.write(fd, b"\r")
                self.enter_at = None
                self.state.write("busy")   # UserPromptSubmit hook will confirm
            return
        if not self.pending:
            return
        if self.state.value != "idle":
            return
        if now - self.state.since < self.cfg["submitDelayMs"] / 1000:
            return
        if now - self.last_key < self.cfg["typingGraceMs"] / 1000:
            return
        text = self.pending.popleft()
        os.write(fd, b"\x1b[200~" + text.encode() + b"\x1b[201~")
        self.enter_at = now + 0.25
        self.set_status(self.status)

    def run(self) -> int:
        if self.cfg["speakReplies"]:
            self.args = ["--append-system-prompt", self.cfg["speakPrompt"], *self.args]
        env = dict(os.environ, CLAUDE_VOICE_STATE=self.state_path, CLAUDE_VOICE_STATUS=self.status_path,
                   CLAUDE_VOICE_CTL=self.ctl_path)
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe(self.cfg["claudeCommand"], [self.cfg["claudeCommand"], *self.args], env)

        stdin = sys.stdin.fileno()
        stdout = sys.stdout.fileno()
        interactive = os.isatty(stdin)

        def sync_size(*_):
            if interactive:
                size = fcntl.ioctl(stdin, termios.TIOCGWINSZ, b"\0" * 8)
                fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
                os.kill(pid, signal.SIGWINCH)

        sync_size()
        signal.signal(signal.SIGWINCH, sync_size)
        saved = termios.tcgetattr(stdin) if interactive else None
        if interactive:
            tty.setraw(stdin)

        self.set_status("starting")
        self.listener = Listener(self.cfg, self.on_event)
        if self.cfg["continuousVoice"]:
            try:
                self.listener.start()
            except Exception as e:  # noqa: BLE001
                self.on_event("error", f"microphone unavailable: {e}")
        else:
            self.set_status("off")

        code = 0
        try:
            while True:
                try:
                    r, _, _ = select.select([fd, stdin], [], [], 0.05)
                except InterruptedError:
                    continue
                if fd in r:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        data = b""
                    if not data:
                        break
                    os.write(stdout, data)
                    self.last_output = time.monotonic()
                if stdin in r:
                    data = os.read(stdin, 4096)
                    if not data:
                        break
                    if self.toggle_seq in data:
                        data = data.replace(self.toggle_seq, b"")
                        self.toggle()
                    if self.speak_seq in data:
                        data = data.replace(self.speak_seq, b"")
                        self.toggle_speaking()
                    if data:
                        self.last_key = time.monotonic()
                        os.write(fd, data)
                while not self.events.empty():
                    kind, payload = self.events.get_nowait()
                    if kind == "status":
                        self.set_status(payload)
                    elif kind == "text":
                        self.handle_text(payload)
                    elif kind == "error":
                        self.set_status(f"⚠️  {payload}")
                self.poll_ctl()
                self.state.poll(self.last_output, self.last_key)
                self.try_inject(fd)
        finally:
            if interactive:
                termios.tcsetattr(stdin, termios.TCSAFLUSH, saved)
            if self.listener:
                self.listener.stop()
            try:
                _, status = os.waitpid(pid, 0)
                code = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                pass
            for p in (self.state_path, self.status_path, self.ctl_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return code


def main() -> int:
    cfg = load_config()
    args = sys.argv[1:]
    if args[:1] == ["--voice-off"]:
        cfg["continuousVoice"] = False
        args = args[1:]
    return VoiceSession(cfg, args).run()


if __name__ == "__main__":
    sys.exit(main())
