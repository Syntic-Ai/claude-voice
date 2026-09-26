"""Send words, word mode, sleep/wake, interrupt, dialog answers, vocabulary — real speech through the real pipeline."""
import json, os, sys, tempfile, time
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "tests"))
import claude_voice as cv
from test_pipeline_helpers import speech, silence, SR

cv.RUN_DIR = tempfile.mkdtemp()
os.environ["CLAUDE_VOICE_CONFIG"] = os.path.join(cv.RUN_DIR, "cfg.json")   # never touch the real config

def session(**over):
    s = cv.VoiceSession(dict(cv.load_config(), sounds=False, silenceMs=10000, **over), [])
    s.state.write("idle")
    return s

# ── 1. phrase matching (pure) ──
s = session()
for t in ["Check the horses, go go.", "Check the horses. Gogo!", "fix it, finish", "Refactor that. Do it.", "Send it."]:
    assert s.ends_with_send(cv.normalize(t)), t
for t in ["Check the horses.", "I want to go", "finished"]:
    assert not s.ends_with_send(cv.normalize(t)), t
assert s.strip_send("Check the horses, go go.") == "Check the horses"
assert s.strip_send("Check the horses. Gogo!") == "Check the horses"
assert s.strip_send("Fix the login bug. Finish.") == "Fix the login bug"
assert [cv.spoken_index(x) for x in ["option two", "number 3", "the second one", "2", "option to"]] == [1, 2, 1, 1, 1]
print("1 phrase matching OK")

# ── 2. dialog answers → keys only ──
s = session(); s.state.write("waiting-permission")
assert s.answer("yes") and list(s.keyq) == [b"\r"] and s.state.value == "busy"
s = session(); s.state.write("waiting-permission")
assert s.answer("always") and list(s.keyq) == [b"\x1b[B", b"\r"]
s = session(); s.state.write("waiting-permission")
assert s.answer("no use pnpm instead") and list(s.keyq) == [b"\x1b"] and list(s.pending) == ["use pnpm instead"]
s = session(); s.state.write("waiting-question")
json.dump({"tool_input": {"questions": [{"question": "Color?", "options": [{"label": "Red"}, {"label": "Green"}, {"label": "Blue"}]}]}},
          open(s.state_path + ".payload", "w"))
assert s.answer("green") and list(s.keyq) == [b"\x1b[B", b"\r"]
s.keyq.clear(); s.state.write("waiting-question"); s.question_index = 0
assert s.answer("the third one") and list(s.keyq) == [b"\x1b[B", b"\x1b[B", b"\r"]
s.keyq.clear(); s.state.write("waiting-question")
assert not s.answer("tell me a joke")                       # unknown → nothing typed
s = session(); assert not s.answer("yes")                   # idle: not a dialog answer
print("2 dialog answers OK")

# ── 3-6. real audio through Listener + peeks ──
def play(s, audio, speed=3.0):
    """Feed audio through the real listener faster than real time; return [(audio_sec, event)]."""
    lst = cv.Listener(s.cfg, s.on_event, s.decide); s.listener = lst; lst.enabled = True
    while lst.transcriber is None: time.sleep(0.1)
    r, w = os.pipe()
    pcm = (np.clip(audio + np.random.default_rng(0).normal(0, .002, audio.size), -1, 1) * 32767).astype(np.int16).tobytes()
    n, log = cv.FRAME_SAMPLES * 2, []
    for i in range(0, len(pcm) - n + 1, n):
        lst.frames.put(pcm[i:i + n]); time.sleep(cv.FRAME_MS / 1000 / speed)
        before = (len(s.pending), len(s.draft), s.sleeping)
        s.process_events(w)
        after = (len(s.pending), len(s.draft), s.sleeping)
        if after != before: log.append((round(i / 2 / SR, 1), after))
    time.sleep(3); s.process_events(w)
    os.close(w); keys = os.read(r, 100) if False else b""
    return log

cfg0 = cv.load_config()
# 3. "both" mode: send word submits right away instead of waiting 10 s
s = session()
said = speech("Check the rooftop playground, go go.")
log = play(s, np.concatenate([silence(1), said, silence(11)]), speed=1.0)   # real time: honest latency
end = 1 + len(said) / SR
print("   send-word events:", log, "| speech ended at", round(end, 1))
assert list(s.pending) == ["Check the rooftop playground"] or cv.normalize(s.pending[0]) == "check the rooftop playground", s.pending
assert log[0][0] < end + 4, "must submit within seconds, not after 10 s of silence"
print("3 send word (instant) OK")

# 4. word mode: pauses never send; everything is collected until "finish"
s = session(submitMode="word")
a, b, f = speech("Check the rooftop."), speech("Then test the horses."), speech("Finish.")
log = play(s, np.concatenate([silence(1), a, silence(4), b, silence(6), f, silence(4)]))
print("   word-mode events:", log, "| pending:", list(s.pending))
assert len(s.pending) == 1 and "rooftop" in s.pending[0].lower() and "horses" in s.pending[0].lower()
assert all(p == 0 for _, (p, d, z) in log[:-1]), "nothing may be sent before the send word"
print("4 word mode OK")

# 5. sleep / wake by voice: nothing gets through while asleep
s = session()
log = play(s, np.concatenate([silence(1), speech("Voice off."), silence(3), speech("Delete the database."), silence(3),
                              speech("Voice on."), silence(3)]), speed=1.0)
print("   sleep events:", log, "| sleeping:", s.sleeping, "| pending:", list(s.pending))
assert not s.sleeping and not s.pending and any(z for _, (_, _, z) in log)
print("5 sleep/wake OK")

# 6. interrupt while busy → Esc
s = session(); s.state.write("busy")
lst = cv.Listener(s.cfg, s.on_event, s.decide)
while lst.transcriber is None: time.sleep(0.1)
assert s.decide("Stop.", True) == "consume"
r, w = os.pipe(); s.state.write("busy"); s.process_events(w); os.close(w)
assert os.read(r, 10) == b"\x1b"
print("6 interrupt OK")

# 7. vocabulary
tr_plain = cv.Transcriber(dict(cfg0, vocabulary=[]))
tr_vocab = cv.Transcriber(dict(cfg0, vocabulary=["Syntic", "SynteraX", "XCHATS"]))
clip = speech("Deploy Syntic and SynteraX.")
pcm = (clip * 32767).astype(np.int16).tobytes()
p, v = tr_plain.transcribe(pcm), tr_vocab.transcribe(pcm)
print(f"   without vocabulary: {p!r}\n   with vocabulary:    {v!r}")
assert "Syntic" in v and "SynteraX" in v
print("7 vocabulary OK")
print("FEATURES OK")
