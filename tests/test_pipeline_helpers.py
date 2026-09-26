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

