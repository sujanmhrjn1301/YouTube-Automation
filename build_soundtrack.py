import os
import subprocess
from pathlib import Path
from src.config import settings

FFMPEG = settings.FFMPEG_PATH
audio_dir = Path("assets/audio")
out_bgm = audio_dir / "full_narrative_bgm.wav"

# Create full 480s background music track with narrative transitions
cmd = [
    FFMPEG, "-y",
    "-stream_loop", "-1", "-i", str(audio_dir / "bgm_boss_fight.mp3"),   # [0] boss fight
    "-stream_loop", "-1", "-i", str(audio_dir / "bgm_suspense.mp3"),     # [1] suspense
    "-filter_complex",
    (
        # Act 0: 0 to 24s boss music
        "[0:a]atrim=0:24,afade=t=in:st=0:d=1,afade=t=out:st=22:d=2[act0_m];"
        # Act 1 & 2: 24 to 212s (188s) suspense music
        "[1:a]atrim=0:188,afade=t=in:st=0:d=2,afade=t=out:st=185:d=3[act12_m];"
        # Act 3 & 4: 212 to 452s (240s) boss fight music
        "[0:a]atrim=15:255,afade=t=in:st=0:d=2,afade=t=out:st=236:d=4[act34_m];"
        # Act 5: 452 to 480s (28s) suspense outro fade
        "[1:a]atrim=40:68,afade=t=in:st=0:d=2,afade=t=out:st=24:d=4[act5_m];"
        # Concat all segments
        "[act0_m][act12_m][act34_m][act5_m]concat=n=4:v=0:a=1[bgm_full]"
    ),
    "-map", "[bgm_full]",
    "-c:a", "pcm_s16le",
    "-t", "480",
    str(out_bgm)
]

print("Assembling narrative soundtrack...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode == 0 and out_bgm.exists():
    print(f"Soundtrack generated: {out_bgm.name} ({out_bgm.stat().st_size / 1024 / 1024:.2f} MB)")
else:
    print("Error generating soundtrack:", res.stderr[-500:])
