import os
import subprocess
from pathlib import Path
from src.config import settings

FFMPEG = settings.FFMPEG_PATH
temp_dir = Path("output/longform_videos/temp/longform_1792507333")
broll_file = Path("assets/broll/broll_teaser_zoom.mp4")
test_out = temp_dir / "test_act0_vfx_with_broll.mp4"

font_file = "C\\:/Windows/Fonts/segoeuib.ttf"

# Test overlay-based dynamic punch in + B-Roll Cutaway + HUD + vignette
filter_complex = (
    # 1. Prepare B-roll cutaway (scaled to 1920x1080 with 0.3s fast crossfade)
    "[1:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
    "format=yuva420p,fade=t=in:st=0.8:d=0.3:alpha=1,fade=t=out:st=3.2:d=0.3:alpha=1[broll_faded];"
    # 2. Overlay B-roll onto base video between 0.8s and 3.5s
    "[0:v][broll_faded]overlay=0:0:enable='between(t\\,0.8\\,3.5)'[v_broll];"
    # 3. Dynamic Punch-In between 5.5s and 12.0s
    "[v_broll]split=2[v_base2][v_for_zoom];"
    "[v_for_zoom]scale=1.22*1920:1.22*1080,crop=1920:1080[v_zoomed];"
    "[v_base2][v_zoomed]overlay=0:0:enable='between(t\\,5.5\\,12.0)'[v_paced];"
    # 4. Glassmorphic lower third card
    "[v_paced]drawbox=y=ih-140:color=black@0.75:width=iw:height=90:t=fill:enable='between(t\\,0.5\\,5.0)',"
    "drawbox=y=ih-142:color=0x00E5FF@0.9:width=iw:height=4:t=fill:enable='between(t\\,0.5\\,5.0)',"
    f"drawtext=fontfile='{font_file}':text='TEASER\\: THE WARDEN AWAKENS':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=h-118:enable='between(t\\,0.5\\,5.0)',"
    # 5. Top HUD Warning Badge
    "drawbox=y=40:color=black@0.75:width=iw:height=60:t=fill:enable='between(t\\,12.5\\,19.0)',"
    "drawbox=y=98:color=0xFF2222@0.9:width=iw:height=3:t=fill:enable='between(t\\,12.5\\,19.0)',"
    f"drawtext=fontfile='{font_file}':text='[!] THREAT DETECTED\\: DEEP DARK MOB':fontcolor=0xFFFF00:fontsize=28:x=(w-text_w)/2:y=56:enable='between(t\\,12.5\\,19.0)',"
    # 6. Pulsing Darkness Vignette
    "vignette='PI/4+0.25*sin(2*PI*(t-13)/2.5)':mode=backward:eval=frame:enable='between(t\\,13.0\\,21.0)'[v_final]"
)

cmd = [
    FFMPEG, "-y",
    "-i", str(temp_dir / "act_0_4210_4234.mp4"),
    "-i", str(broll_file),
    "-filter_complex", filter_complex,
    "-map", "[v_final]",
    "-map", "0:a",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
    "-c:a", "copy",
    str(test_out)
]

print("Rendering test Act 0 with B-Roll cutaway...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode == 0 and test_out.exists():
    print(f"B-Roll Render Success! Output: {test_out.name} ({test_out.stat().st_size / 1024 / 1024:.2f} MB)")
else:
    print("Error:", res.stderr[-500:])
