import os
import subprocess
from pathlib import Path

FFMPEG_DIR = r"C:\ffmpeg\bin"
env = os.environ.copy()
if os.path.exists(FFMPEG_DIR):
    env["PATH"] = FFMPEG_DIR + os.pathsep + env.get("PATH", "")

assets_audio = Path("assets/audio")
assets_broll = Path("assets/broll")
assets_audio.mkdir(parents=True, exist_ok=True)
assets_broll.mkdir(parents=True, exist_ok=True)

def run(cmd):
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print("ERROR:", res.stderr[:300])
    else:
        print("DONE")

# 1. Whoosh SFX (short 1-2 sec)
whoosh_out = assets_audio / "sfx_whoosh.wav"
if not whoosh_out.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:01-0:04",
        "-x", "--audio-format", "wav",
        "-o", str(whoosh_out),
        "https://www.youtube.com/watch?v=pqEn9icjK0I"
    ])

# 2. Heartbeat SFX (short 3-4 sec)
heartbeat_out = assets_audio / "sfx_heartbeat.wav"
if not heartbeat_out.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:01-0:06",
        "-x", "--audio-format", "wav",
        "-o", str(heartbeat_out),
        "https://www.youtube.com/watch?v=4Grg4D9wHqk"
    ])

# 3. Suspense BGM
suspense_out = assets_audio / "bgm_suspense.mp3"
if not suspense_out.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:10-2:40",
        "-x", "--audio-format", "mp3",
        "-o", str(suspense_out),
        "https://www.youtube.com/watch?v=A318d_MsL18"
    ])

# 4. Boss fight BGM
boss_out = assets_audio / "bgm_boss_fight.mp3"
if not boss_out.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:05-2:35",
        "-x", "--audio-format", "mp3",
        "-o", str(boss_out),
        "https://www.youtube.com/watch?v=4_XW1R0Na1I"
    ])

# 5. Ancient City Pan B-roll (1080p, 6 sec)
city_broll = assets_broll / "ancient_city_pan.mp4"
if not city_broll.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:15-0:21",
        "-f", "bestvideo[height<=1080]+bestaudio/best",
        "-o", str(city_broll),
        "https://www.youtube.com/watch?v=Q61XYOYcu4A"
    ])

# 6. Warden Emergence B-roll (1080p, 6 sec)
warden_broll = assets_broll / "warden_emergence.mp4"
if not warden_broll.exists():
    run([
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_DIR,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", "*0:46-0:53",
        "-f", "bestvideo[height<=1080]+bestaudio/best",
        "-o", str(warden_broll),
        "https://www.youtube.com/watch?v=Au4gUvCUzYQ"
    ])

print("Asset downloads completed!")
