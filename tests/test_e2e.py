"""End-to-end: real `claude` in a PTY, speech fed as audio, no keyboard. Checks auto-submit + queueing."""
import glob, json, os, pty, re, select, subprocess, sys, tempfile, time, wave
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
from test_pipeline_helpers import speech, silence, SR  # noqa

d = tempfile.mkdtemp()
audio = np.concatenate([silence(8), speech("Reply with only the word banana, in capital letters."),
                        silence(2.2), speech("Now reply with only the word horses, in capital letters."),
                        silence(40)])
wav = os.path.join(d, "t.wav")
with wave.open(wav, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(audio + np.random.default_rng(1).normal(0, .002, audio.size), -1, 1) * 32767).astype(np.int16).tobytes())
cfgp = os.path.join(d, "cfg.json")
json.dump({**(json.load(open(os.path.join(REPO, "config.json"))) if os.path.exists(os.path.join(REPO, "config.json")) else {}), "silenceMs": 1500, "sounds": False}, open(cfgp, "w"))

work = os.path.realpath(tempfile.mkdtemp())
proj = os.path.expanduser("~/.claude/projects/") + re.sub(r"[^a-zA-Z0-9]", "-", work)
before = set(glob.glob(proj + "/*.jsonl"))
env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}  # run as a top-level session
env.update(CLAUDE_VOICE_TEST_AUDIO=wav, CLAUDE_VOICE_CONFIG=cfgp)
pid, fd = pty.fork()
if pid == 0:
    os.chdir(work)
    os.execvpe(os.path.join(REPO, "claude-voice"), ["claude-voice", "--model", "haiku"], env)
screen, t0, trusted = b"", time.time(), False
while time.time() - t0 < float(os.environ.get("E2E_SECS", 75)):
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try: screen += os.read(fd, 65536)
        except OSError: break
    plain = re.sub(rb"\x1b\[[0-9;?]*[a-zA-Z]", b"", screen)
    if not trusted and b"trustthisfolder" in plain.replace(b" ", b"").lower():
        time.sleep(1); os.write(fd, b"\x1b[B"); time.sleep(0.3); os.write(fd, b"\r"); trusted = True   # one-time folder-trust dialog only
os.kill(pid, 9); open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_screen.txt"), "wb").write(screen)
new = set(glob.glob(proj + "/*.jsonl")) - before
assert new, "no session transcript created"
rows = [json.loads(l) for l in open(max(new, key=os.path.getmtime))]
convo = []
for r in rows:
    if r.get("type") == "user" and isinstance(r["message"]["content"], str):
        convo.append(("USER", r["timestamp"], r["message"]["content"]))
    if r.get("type") == "assistant":
        for c in r["message"]["content"]:
            if c.get("type") == "text": convo.append(("CLAUDE", r["timestamp"], c["text"]))
for c in convo: print(*c)
kinds = [k for k, _, _ in convo]
assert kinds == ["USER", "CLAUDE", "USER", "CLAUDE"], kinds
assert "BANANA" in convo[1][2] and "HORSES" in convo[3][2]
assert convo[2][1] > convo[1][1], "2nd utterance must be submitted only after Claude finished the 1st"
print("E2E OK")
