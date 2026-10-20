---
name: motion-graphics-editor
description: >-
  Advanced motion graphics, kinetic subtitles, camera punch-ins, audio ducking,
  and pacing effects for high-retention YouTube longform and gaming videos.
---

# Motion Graphics & Visual Pacing Skill

This skill provides precise FFmpeg, ASS/SSA subtitle scripting, and animation rules for adding motion graphics, kinetic typography, dynamic camera movement, and audio polish to YouTube videos.

---

## 1. Visual Pacing & Dynamic Punch-Ins

### A. 1.18x Punch-In Zoom (Reaction / Comedic / Scared moments)
Punching in by 15-20% on the creator's face or game crosshair changes visual stimulus without requiring a multi-camera setup.

```bash
# Standard 1.18x Center Punch-in Zoom
ffmpeg -i in.mp4 -vf "scale=1.18*iw:1.18*ih,crop=iw/1.18:ih/1.18:(1.18*iw-iw)/2:(1.18*ih-ih)/2" -c:a copy punch.mp4
```

### B. Subtle Slow Creep-in (Rising Tension)
```bash
# Slowly zooms from 1.0x to 1.10x over 5 seconds
ffmpeg -i in.mp4 -vf "zoompan=z='min(zoom+0.0015,1.10)':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30" -c:a copy slow_zoom.mp4
```

---

## 2. Kinetic Subtitles & Typography (ASS Format)

YouTube retention drops when viewers cannot follow frantic audio (e.g. screaming, Discord crosstalk, explosions). Bold, animated, centered subtitles maintain visual focus.

### A. The "MrBeast / Hormozi" High-Impact Style
- Font: **Montserrat Black**, **The Bold Font**, or **Komika Axis**
- Size: 64–76px (1080p canvas)
- Colors:
  - Primary text: Clean Pure White (`&HFFFFFF&`)
  - Accent / Keywords: High-Voltage Yellow (`&H00E5FF&` in BGR) or Neon Cyan (`&HFFFF00&` in BGR)
  - Outline: 4.5px Solid Charcoal/Black (`&H000000&`)
  - Shadow: 2.5px Deep Drop Shadow (`&H000000&`)

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,The Bold Font,68,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1.5,0,1,4.5,2.5,2,40,40,90,1
Style: Highlight,The Bold Font,72,&H0000E5FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,105,105,2.0,0,1,5.0,3.0,2,40,40,90,1
```

---

## 3. Narrative Chapter Cards & Lower Thirds

Use clean, semi-transparent letterbox cards to demarcate Acts (e.g., "ACT 1: THE MISSION", "ACT 3: THE WARDEN AWAKENS").

```bash
# Draws high-contrast act header with smooth fade-in
ffmpeg -i in.mp4 -vf "drawbox=y=ih-140:color=black@0.65:width=iw:height=100:t=fill,drawtext=text='ACT 3\\: THE WARDEN AWAKENS':fontcolor=white:fontsize=44:fontfile='C\\:/Windows/Fonts/arialbd.ttf':x=(w-text_w)/2:y=h-115:enable='between(t,0.5,5.5)'" -c:a copy act_card.mp4
```

---

## 4. Professional YouTube Audio Mastering

### A. EBU R128 Dual-Pass Loudness Normalization
YouTube normalizes longform uploads to **-14 LUFS**. Exceeding it results in YouTube turning your video down; failing to reach it makes your video too quiet.

```bash
# Pass 1: Measure audio integrated loudness
ffmpeg -i input.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null -

# Pass 2: Apply linear normalization
ffmpeg -i input.mp4 -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-22.4:measured_TP=-4.1:measured_LRA=12.1:measured_thresh=-33.5:offset=0.2" -c:v copy mastered.mp4
```

### B. Dialogue Ducking with Sidechain
When background music is playing, duck music by **-14dB** whenever dialogue exceeds -28dB:
```bash
ffmpeg -i speech.wav -i music.mp3 -filter_complex "[1:a]volume=0.35[bg];[bg][0:a]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=350[ducked];[0:a][ducked]amix=inputs=2:duration=first[out]" -map "[out]" final_mix.wav
```
