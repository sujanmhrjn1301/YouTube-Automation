import subprocess
from pathlib import Path
from src.config import settings

FFMPEG = settings.FFMPEG_PATH
temp_dir = Path("output/longform_videos/temp/longform_1792507333")
broll_dir = Path("assets/broll")
broll_dir.mkdir(parents=True, exist_ok=True)

# 1. Teaser Close-up B-roll (3 sec)
subprocess.run([
    FFMPEG, "-y",
    "-ss", "2", "-t", "3.5",
    "-i", str(temp_dir / "act_0_4210_4234.mp4"),
    "-vf", "scale=1.28*1920:1.28*1080,crop=1920:1080,eq=contrast=1.3:saturation=1.35",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-an",
    str(broll_dir / "broll_teaser_zoom.mp4")
], check=True)

# 2. Ancient City Exploration B-roll (4 sec)
subprocess.run([
    FFMPEG, "-y",
    "-ss", "20", "-t", "4",
    "-i", str(temp_dir / "act_2_4020_4126.mp4"),
    "-vf", "scale=1920:1080,eq=contrast=1.2:saturation=1.3",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-an",
    str(broll_dir / "broll_ancient_city.mp4")
], check=True)

# 3. Warden Encounter Dramatic B-roll (4 sec)
subprocess.run([
    FFMPEG, "-y",
    "-ss", "14", "-t", "4",
    "-i", str(temp_dir / "act_3_4234_4354.mp4"),
    "-vf", "scale=1.22*1920:1.22*1080,crop=1920:1080,vignette=PI/4,eq=contrast=1.3:saturation=1.25",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-an",
    str(broll_dir / "broll_warden_encounter.mp4")
], check=True)

print("All B-roll clips prepared cleanly!")
