import numpy as np
import wave
from pathlib import Path

sample_rate = 44100
assets_audio = Path("assets/audio")
assets_audio.mkdir(parents=True, exist_ok=True)

def save_wav(filename: Path, data: np.ndarray):
    data = np.clip(data, -1.0, 1.0)
    int_data = (data * 32767).astype(np.int16)
    with wave.open(str(filename), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(int_data.tobytes())
    print(f"Generated {filename.name} ({len(data)/sample_rate:.2f}s)")

# 1. Whoosh SFX (0.8s)
dur = 0.8
t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
noise = np.random.uniform(-1, 1, len(t))
# Frequency modulation envelope: peak at t=0.35s
env = np.exp(-((t - 0.35) ** 2) / 0.025)
# Filter simulation with sine sweeping
carrier = np.sin(2 * np.pi * (300 + 1200 * np.exp(-((t - 0.35)**2)/0.03)) * t)
whoosh = (noise * 0.7 + carrier * 0.3) * env
# Add low rumble
whoosh += np.sin(2 * np.pi * 90 * t) * env * 0.5
save_wav(assets_audio / "sfx_whoosh.wav", whoosh * 0.85)

# 2. Heartbeat Double-Thump SFX (1.5s)
dur_hb = 1.5
t_hb = np.linspace(0, dur_hb, int(sample_rate * dur_hb), endpoint=False)
hb = np.zeros_like(t_hb)
# First beat at t=0.1s
t1 = t_hb - 0.1
mask1 = t1 >= 0
env1 = np.exp(-t1[mask1] * 18.0) * mask1[mask1]
hb[mask1] += np.sin(2 * np.pi * 55 * t1[mask1]) * env1 * 0.9
# Second beat at t=0.38s
t2 = t_hb - 0.38
mask2 = t2 >= 0
env2 = np.exp(-t2[mask2] * 22.0) * mask2[mask2]
hb[mask2] += np.sin(2 * np.pi * 48 * t2[mask2]) * env2 * 0.7
save_wav(assets_audio / "sfx_heartbeat.wav", hb * 0.95)

# 3. Sub-Bass Drop / Warden Rumble (2.5s)
dur_sub = 2.5
t_sub = np.linspace(0, dur_sub, int(sample_rate * dur_sub), endpoint=False)
# Pitch envelope sliding from 95Hz down to 32Hz
freq = 95.0 * np.exp(-t_sub * 0.9) + 30.0
phase = 2 * np.pi * np.cumsum(freq) / sample_rate
env_sub = np.exp(-t_sub * 1.1)
sub_drop = np.sin(phase) * env_sub
# Add subtle saturation / grit
sub_drop = np.tanh(sub_drop * 1.8) * 0.85
save_wav(assets_audio / "sfx_sub_drop.wav", sub_drop)

print("All SFX generated successfully!")
