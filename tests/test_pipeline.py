"""Audio pipeline test: synthesized speech + noise -> Segmenter -> Whisper."""
import os, subprocess, sys, tempfile, time, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import claude_voice as cv

SR = 16000

def speech(text):
    d = tempfile.mkdtemp()
    aiff, wav = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
    subprocess.run(["say", "-o", aiff, text], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", aiff, "-ar", str(SR), "-ac", "1", wav], check=True)
    with wave.open(wav) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

def silence(sec): return np.zeros(int(SR * sec), np.float32)

def run(audio, cfg):
    rng = np.random.default_rng(0)
    audio = audio + rng.normal(0, 0.002, audio.size).astype(np.float32)  # room noise
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    seg, out, n = cv.Segmenter(cfg), [], cv.FRAME_SAMPLES * 2
    for i in range(0, len(pcm) - n + 1, n):
        u = seg.feed(pcm[i:i + n])
        if u: out.append((i / 2 / SR, u))
    return out

cfg = dict(cv.load_config(), silenceMs=1300)
click = np.zeros(int(SR * 0.08), np.float32); click[::40] = 0.6          # short noise burst
a1a, a1b = speech("Check the rooftop"), speech("playground again.")
a2 = speech("Now test the horses.")
audio = np.concatenate([silence(1), click, silence(1.5), a1a, silence(0.6), a1b,
                        silence(2.0), a2, silence(2.0)])
utts = run(audio, cfg)
print(f"utterances detected: {len(utts)} (expect 2)")
tr = cv.Transcriber(cfg)
texts = []
for end_t, u in utts:
    t0 = time.time(); txt = tr.transcribe(u); dt = time.time() - t0
    texts.append(txt)
    print(f"  ended at {end_t:5.2f}s  len {len(u)/2/SR:4.2f}s  transcribe {dt:4.2f}s  -> {txt!r}")
assert len(utts) == 2, "expected exactly 2 utterances (click ignored, mid-sentence pause not split)"
assert "rooftop playground" in cv.normalize(texts[0]), texts[0]
assert "horses" in texts[1].lower(), texts[1]
# noise-only input must produce nothing
assert run(np.concatenate([silence(1), click, silence(0.3), click, silence(2)]), cfg) == []
assert cv.clean_transcript(" Thank you. ") == "" and cv.clean_transcript("/clear the cache") == "clear the cache"
assert cv.normalize("Voice off.") in cfg["stopPhrases"]
# far-field: whole thing at 1/10 volume, with 10 s end-of-speech; a 4 s thinking pause must NOT split
far = dict(cfg, silenceMs=10000)
quiet = np.concatenate([silence(1), a1a, silence(4.0), a1b, silence(10.5), a2 * 1.0, silence(10.5)]) * 0.1
u2 = run(quiet, far)
print("far-field utterances:", len(u2), [round(t,1) for t,_ in u2], [tr.transcribe(u) for _,u in u2])
assert len(u2) == 2
assert u2[0][0] > 1 + len(a1a)/SR + 4 + len(a1b)/SR + 9.9, "must wait ~10 s of silence before ending"
print("PIPELINE OK")
