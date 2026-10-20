import subprocess
from pathlib import Path
from src.config import settings

FFMPEG = settings.FFMPEG_PATH
audio_dir = Path("assets/audio")
bgm_file = audio_dir / "full_narrative_bgm.wav"
whoosh = audio_dir / "sfx_whoosh.wav"
heartbeat = audio_dir / "sfx_heartbeat.wav"
sub_drop = audio_dir / "sfx_sub_drop.wav"
out_master = audio_dir / "master_audio_bed.wav"

cmd = [
    FFMPEG, "-y",
    "-i", str(bgm_file),     # [0] 480s BGM
    "-i", str(whoosh),       # [1] Whoosh
    "-i", str(sub_drop),     # [2] Sub-bass drop
    "-i", str(heartbeat),    # [3] Heartbeat
    "-filter_complex",
    (
        # Whoosh at t=0.5s, 24.5s, 106.5s, 212.5s, 332.5s, 452.5s
        "[1:a]asplit=6[w0][w1][w2][w3][w4][w5];"
        "[w0]adelay=500|500,volume=1.2[w0_d];"
        "[w1]adelay=24500|24500,volume=1.2[w1_d];"
        "[w2]adelay=106500|106500,volume=1.2[w2_d];"
        "[w3]adelay=212500|212500,volume=1.2[w3_d];"
        "[w4]adelay=332500|332500,volume=1.2[w4_d];"
        "[w5]adelay=452500|452500,volume=1.2[w5_d];"
        # Sub drop at t=0.5s, 212.5s, 332.5s
        "[2:a]asplit=3[sb0][sb1][sb2];"
        "[sb0]adelay=500|500,volume=1.0[sb0_d];"
        "[sb1]adelay=212500|212500,volume=1.1[sb1_d];"
        "[sb2]adelay=332500|332500,volume=1.1[sb2_d];"
        # Heartbeats at t=150.0s, 215.0s, 225.0s, 235.0s
        "[3:a]asplit=4[hb0][hb1][hb2][hb3];"
        "[hb0]adelay=150000|150000,volume=1.3[hb0_d];"
        "[hb1]adelay=215000|215000,volume=1.4[hb1_d];"
        "[hb2]adelay=225000|225000,volume=1.4[hb2_d];"
        "[hb3]adelay=235000|235000,volume=1.4[hb3_d];"
        # Mix SFX and BGM together
        "[0:a][w0_d][w1_d][w2_d][w3_d][w4_d][w5_d][sb0_d][sb1_d][sb2_d][hb0_d][hb1_d][hb2_d][hb3_d]amix=inputs=14:duration=first:dropout_transition=0[bed]"
    ),
    "-map", "[bed]",
    "-c:a", "pcm_s16le",
    "-t", "480",
    str(out_master)
]

print("Mixing master audio bed with SFX...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode == 0 and out_master.exists():
    print(f"Master audio bed ready: {out_master.name} ({out_master.stat().st_size / 1024 / 1024:.2f} MB)")
else:
    print("Error:", res.stderr[-500:])
