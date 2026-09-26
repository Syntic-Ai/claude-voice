import os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import claude_voice as cv
cv.RUN_DIR = tempfile.mkdtemp()
os.environ["CLAUDE_VOICE_CONFIG"] = os.path.join(cv.RUN_DIR, "cfg.json")
class FakeListener:
    enabled = True
    def stop(self): self.enabled = False
s = cv.VoiceSession(dict(cv.load_config(), sounds=False), [])
s.listener = FakeListener()
s.state.write("busy")
s.handle_text("Now test the horses."); s.handle_text("And the rooftop.")
assert list(s.pending) == ["Now test the horses.", "And the rooftop."]      # queued while busy
s.handle_text("Scratch that."); assert not s.pending                           # cancel phrase
s.handle_text("Voice off."); assert s.sleeping and s.listener.enabled         # spoken stop = sleep (wake word only)
s.handle_text("Delete everything"); assert not s.pending                        # ignored while asleep
s.sleeping = False
s2 = cv.VoiceSession(dict(cv.load_config(), sounds=False, whileBusy="ignore"), []); s2.listener = FakeListener()
s2.state.write("busy"); s2.handle_text("dropped"); assert not s2.pending          # ignore mode
assert s2.state.value == "busy"
s2.state.write("waiting"); assert s2.state.poll(0, 0) == "waiting"             # dialog open: never inject
print("COMMANDS OK")

# ── controls: `voice` CLI via ctl file, mute phrases, speak flag ──
import subprocess
s3 = cv.VoiceSession(dict(cv.load_config(), sounds=False), [])
class L2(FakeListener):
    def start(self): self.enabled = True
s3.listener = L2()
s3.toggle = lambda: setattr(s3.listener, "enabled", not s3.listener.enabled)
vc = os.path.join(REPO, "voice")
env = dict(os.environ, CLAUDE_VOICE_CTL=s3.ctl_path, CLAUDE_VOICE_STATUS=s3.status_path)
import time
subprocess.run([vc, "off"], env=env, check=True, capture_output=True); time.sleep(0.02); s3.poll_ctl()
assert s3.listener.enabled is False, "voice off"
subprocess.run([vc, "on"], env=env, check=True, capture_output=True); time.sleep(0.02); s3.poll_ctl()
assert s3.listener.enabled is True, "voice on"
was = cv.speaking()
subprocess.run([vc, "mute"], env=env, check=True, capture_output=True); assert not cv.speaking()
subprocess.run([vc, "unmute"], env=env, check=True, capture_output=True); assert cv.speaking()
s3.handle_text("Stop talking."); assert not cv.speaking()
s3.handle_text("Talk to me."); assert cv.speaking()
s3.handle_text("Stop talking."); s3.set_status("listening"); assert "🔇" in open(s3.status_path).read()
cv.set_speaking(was)
print("CONTROLS OK")
