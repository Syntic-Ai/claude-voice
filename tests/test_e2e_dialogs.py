"""End-to-end by voice only, against the real `claude`: send word, permission prompt answered "yes",
AskUserQuestion answered by saying the option. The keyboard is only used for the one-time folder-trust dialog."""
import glob, json, os, pty, re, select, sys, tempfile, time, wave
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tests"))
from test_pipeline_helpers import speech, silence, SR

spool, work = tempfile.mkdtemp(), os.path.realpath(tempfile.mkdtemp())
cfgp = os.path.join(spool, "..", os.path.basename(spool) + "-cfg.json")
json.dump({"sounds": False, "speakReplies": False, "silenceMs": 10000}, open(cfgp, "w"))
# Render every clip up front: `say` running would (correctly) trip the echo guard and mute the mic.
LINES = ["Use the Bash tool to run echo hi, redirected into a file named hello.txt. Go go.", "Yes.",
         "Use the AskUserQuestion tool to ask me which color I like, red, green or blue. "
         "When I answer, reply with only that color in capital letters. Go go.", "Green."]
stage, rendered = tempfile.mkdtemp(), {}
for i, text in enumerate(LINES):
    a = np.concatenate([speech(text), silence(1.5)])
    rendered[text] = os.path.join(stage, f"{i:02d}.wav")
    with wave.open(rendered[text], "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(a + np.random.default_rng(i).normal(0, .002, a.size), -1, 1) * 32767).astype(np.int16).tobytes())

def say(text):
    os.rename(rendered[text], os.path.join(spool, os.path.basename(rendered[text])))
    print(f"  🗣  {text}")

env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
env.update(CLAUDE_VOICE_TEST_AUDIO=spool, CLAUDE_VOICE_CONFIG=cfgp)
pid, fd = pty.fork()
if pid == 0:
    os.chdir(work)
    os.execvpe(os.path.join(REPO, "claude-voice"),
               ["claude-voice", "--model", "haiku", "--permission-mode", "default"], env)
state_file = os.path.join(REPO, "run", f"{pid}.state")
screen, trusted = b"", False

def pump(until, timeout, what):
    global screen, trusted
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try: screen += os.read(fd, 65536)
            except OSError: break
        plain = re.sub(rb"\x1b\[[0-9;?<>]*[a-zA-Z~]", b"", screen[-4000:]).replace(b" ", b"").lower()
        if not trusted and b"trustthisfolder" in plain:
            time.sleep(1); os.write(fd, b"\x1b[B"); time.sleep(0.3); os.write(fd, b"\r"); trusted = True
        st = open(state_file).read().strip() if os.path.exists(state_file) else ""
        if until(st):
            print(f"  ✓ {what} (state={st})"); return st
    open(os.path.join(REPO, "tests", "last_screen.txt"), "wb").write(screen)
    raise SystemExit(f"TIMEOUT waiting for: {what} (state={st})")

try:
    pump(lambda st: st == "idle", 60, "claude ready")
    t0 = time.time()
    say(LINES[0])
    pump(lambda st: st == "waiting-permission", 90, "permission prompt shown")
    print(f"    (message sent by send word; prompt appeared {time.time()-t0:.1f}s after speaking started)")
    say("Yes.")
    pump(lambda st: st == "idle" and os.path.exists(os.path.join(work, "hello.txt")), 90, "file created after spoken yes")
    say(LINES[2])
    pump(lambda st: st == "waiting-question", 90, "question shown")
    say("Green.")
    pump(lambda st: st == "idle", 90, "answered and finished")
    time.sleep(2)
finally:
    os.kill(pid, 9)

proj = os.path.expanduser("~/.claude/projects/") + re.sub(r"[^a-zA-Z0-9]", "-", work)
rows = [json.loads(l) for f in glob.glob(proj + "/*.jsonl") for l in open(f)]
texts = [c.get("text", "") for r in rows if r.get("type") == "assistant" for c in r["message"]["content"] if c.get("type") == "text"]
answers = [json.dumps(c.get("content")) for r in rows if r.get("type") == "user" and isinstance(r["message"]["content"], list)
           for c in r["message"]["content"] if c.get("type") == "tool_result"]
print("  hello.txt:", open(os.path.join(work, "hello.txt")).read().strip())
print("  question result:", [a[:120] for a in answers if "olor" in a or "Green" in a][-1:])
print("  final reply:", texts[-1] if texts else None)
assert open(os.path.join(work, "hello.txt")).read().strip() in ("hi", "high")   # Whisper may hear the TTS "hi" as "high"
assert texts and "GREEN" in texts[-1]
print("E2E DIALOGS OK")
