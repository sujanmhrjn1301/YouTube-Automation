---
name: longform-video-editor
description: >-
  Expert video editor workflow for transforming raw multi-hour livestream broadcasts
  and stream VODs into high-retention, YouTube-ready 7 to 9 minute narrative videos.
  Includes pacing curves, dead-air removal, audio leveling, and ffmpeg assembly.
---

# Longform Video Editor Skill: Stream VOD to 7–9 Min YouTube Feature

This skill guides the autonomous extraction, structural storytelling, pacing, and video editing required to transform a raw, unedited live stream (1–4 hours) into a polished, high-engagement **7 to 9 minute** YouTube video that maximizes viewer retention (AVD - Average View Duration).

---

## 1. Core Principles of High-Retention YouTube Editing

A direct cut of a stream is boring. Successful stream-to-video editing requires active structural transformation:

```
[0:00 - 0:25]  ACT 0: The Hook / Teaser (Best peak moment out of context + stake setup)
[0:25 - 1:15]  ACT 1: Context & Goal (What are we doing today? High stakes / objective)
[1:15 - 3:30]  ACT 2: The Struggle / First Obstacles (Rapid pacing, micro-fails, comedic moments)
[3:30 - 5:45]  ACT 3: The Turning Point / Escalation (Rising tension, major breakthrough)
[5:45 - 7:30]  ACT 4: The Climax (The ultimate boss fight, final round, biggest win/loss)
[7:30 - 8:30]  ACT 5: The Aftermath & Outro (Humorous payoff, subscriber call-to-action)
```

### Golden Rules
1. **The 3-Second Retention Rule**: Change visual stimulus (camera angle, punch-in zoom, on-screen text, sound effect) every 3–5 seconds during dialogue; never leave a static frame for > 8 seconds.
2. **Aggressive Dead-Air Trimming**: Remove any pause longer than 0.7 seconds where no one is speaking and nothing visual is happening.
3. **Audio is 60% of the Video**:
   - Normalize speech to -14 LUFS (YouTube's target).
   - Sidechain / Duck background music by -12dB to -15dB whenever the creator is speaking.
   - Use subtle whooshes/impacts on transitions to maintain pacing.
4. **Target Runtime Target**: Strictly between **7 minutes (420 seconds)** and **9 minutes (540 seconds)**.

---

## 2. Multi-Stage Pipeline Architecture

```
[Raw Livestream VOD]
         │
         ▼
[Stage 1: Multi-Modal Ingestion]
   ├── yt-dlp highest quality 1080p60 stream
   ├── Extract 16kHz mono audio for transcription
   └── Silence Detection & Audio Energy Analysis (ffmpeg silencedetect + RMS)
         │
         ▼
[Stage 2: Semantic & Hype Event Detection]
   ├── Whisper timestamps (with filler word detection)
   ├── Pitch/volume spike analysis (laughter, screaming, excitement)
   └── (Optional) YouTube live chat replay replay density spikes
         │
         ▼
[Stage 3: Narrative Architect & Storyboarding (LLM)]
   ├── Ingest transcript with audio energy scores
   ├── Select 10–18 cohesive story beats total
   ├── Construct 6-act storyboard targeting 450–520 seconds
   └── Generate dynamic hook line, chapters, and title options
         │
         ▼
[Stage 4: Automated Assembly & Rough Cut]
   ├── Sub-second precision ffmpeg cut of identified segments
   ├── Automatic dialogue pause tightening (strip silence > 0.7s)
   └── Stitch into unified sequence with zero audio pops
         │
         ▼
[Stage 5: Visual Polish & Pacing FX]
   ├── Dynamic Punch-ins (1.15x zoom on punchlines / intense reactions)
   ├── Fast crossfades / whip-pan transitions between scenes
   └── Highlight captions on key words (punchy animated text on punchlines)
         │
         ▼
[Stage 6: Sound Design & YouTube Audio Mastering]
   ├── EBU R128 2-pass Loudness Normalization (-14 LUFS, -1.0 dB true peak)
   └── Background music layering with automatic dialogue ducking
         │
         ▼
[Stage 7: YouTube Metadata & Thumbnail Packaging]
   ├── High-CTR Title (e.g., "I Survived 10 Days... But It Cost Me Everything")
   ├── Structured Description with Chapters and Timestamps
   └── Frame extraction of the 3 highest emotional moments for Thumbnail
```

---

## 3. FFmpeg Command Recipes

### A. Dead-Air & Silence Detection
Detect long silences to eliminate stream pauses:
```bash
ffmpeg -i input.mp4 -af "silencedetect=noise=-30dB:d=0.8" -f null -
```

### B. High-Precision Lossless Rough Cut
```bash
ffmpeg -ss 00:14:22.500 -to 00:15:45.200 -i input.mp4 -c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k clip1.mp4
```

### C. 1.15x Punch-In Zoom for Comedic/Dramatic Emphasis
```bash
ffmpeg -i clip.mp4 -vf "scale=1.15*iw:1.15*ih,crop=iw/1.15:ih/1.15" -c:a copy punch_in.mp4
```

### D. Audio Normalization to YouTube Standard (-14 LUFS)
```bash
ffmpeg -i assembled.mp4 -af "loudnorm=I=-14:LRA=11:TP=-1.5" -c:v copy mastered_audio.mp4
```

### E. Smooth Scene Transition (Crossfade)
```bash
ffmpeg -i clip1.mp4 -i clip2.mp4 -filter_complex "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=12.0[v];[0:a][1:a]acrossfade=d=0.5[a]" -map "[v]" -map "[a]" joined.mp4
```

---

## 4. Narrative Storyboard Prompt Template

When feeding the transcript to the AI Narrative Architect:
```
You are an elite YouTube Video Editor specialized in turning raw multi-hour livestreams into a 7-9 minute viral video (420 - 540 seconds).

Target Video Length: 480 seconds (8 minutes)
Input: Stream transcript with timestamps and vocal intensity scores.

Rules:
1. Select the main storyline and discard unrelated filler or tangents.
2. Structure the video into:
   - Hook (15-25s): The most intense / hilarious moment from later in the stream.
   - Setup (30-60s): Establish the mission / objective clearly.
   - Escalation (180-240s): 3-5 escalating challenges, misplays, and jokes.
   - Climax (90-120s): The decisive battle / major event.
   - Resolution & Outro (30-45s): The reaction, wrap-up, and subscribe prompt.
3. Total duration of all segments MUST sum to between 420s and 540s.
```
