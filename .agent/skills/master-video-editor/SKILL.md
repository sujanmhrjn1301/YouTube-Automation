---
name: master-video-editor
description: >-
  The definitive, master-level video editing and viral clipping specification.
  Synthesizes elite techniques from industry titans (Hayden Hillier-Smith, Live Speedy,
  MrBeast) into an automated pipeline: narrative triage, cold-open hooks, zero-abrupt-stop
  audio continuity, J/L-cuts, dead-air stripping, dynamic punch-ins, sidechain audio ducking,
  and EBU R128 -14 LUFS mastering.
---

# Master Video Editor & Clipper: The Industry Gold Standard

This master skill is the unified, authoritative guide for transforming raw live broadcasts (1–5 hours), gaming VODs, IRL streams, and longform footage into **irresistible, high-retention 7–9 minute YouTube features** and **59–150s viral Shorts**.

It captures the editing masterclass of **Live Speedy** (IShowSpeed / Kai Cenat official editor) and **Hayden Hillier-Smith** (Logan Paul / MrBeast narrative architect).

---

## 1. The Core Philosophy: Narrative Triage Over Chronological Dumping

A stream is **raw reality**; a YouTube video is a **tightly orchestrated narrative experience**. Viewers do not want a compressed version of everything that happened—they want the *emotional arc* of the event.

### The 6-Act Stream Narrative Architecture (7 to 9 Minutes: 420s – 540s)

```
[0:00 - 0:25]  ACT 0: COLD OPEN / CHAOS TEASER
               • 15–25 seconds of the most intense, funny, or shocking moment from the stream's climax.
               • Cut right BEFORE the ultimate payoff to create intense cognitive curiosity.
               • Hard whoosh / sound riser transition into Act 1.

[0:25 - 1:20]  ACT 1: THE MISSION & THE STAKES
               • Establish the goal in the first 10 seconds ("Today we are getting the new iPhone Duo...").
               • Strip all stream setup, reading chat, donation alerts, and sound checks.
               • Pacing: 1 visual/audio pattern interrupt every 3–4 seconds.

[1:20 - 3:45]  ACT 2: RISING FRICTION & COMEDIC FAILS
               • Micro-arcs of escalating obstacles, arguments, failed attempts, and unexpected glitches.
               • Frankenbiting: Cut pauses > 0.4s between sentences to keep energy relentless.
               • 1.18x punch-in on every high-energy reaction, facepalm, or punchline.

[3:45 - 5:50]  ACT 3: THE TURNING POINT / CRISIS
               • The moment things go completely off the rails or a huge breakthrough happens.
               • Sound design switch: Music shifts from upbeat/comedic to tense/epic.

[5:50 - 7:30]  ACT 4: THE CLIMAX (THE MAIN EVENT)
               • The uncompromised peak of the stream (the confrontation, purchase, boss defeat, unboxing).
               • Rapid pacing, tight cuts, visual zoom pulses on scream/laughter peaks.

[7:30 - 8:30]  ACT 5: THE AFTERMATH & COMEDIC OUTRO
               • The hilarious realization, final reaction, or parting punchline.
               • Smooth 2.5s outro audio/video fade-out with subscribe callout.
```

---

## 2. The Zero-Abrupt-Stop Mandate (Audio & Cut Continuity)

The #1 hallmark of amateur clipping is **abrupt stops**—cutting off someone mid-word, ending on a harsh silent drop, or jumping between clips with clicking audio.

### The Live Speedy Continuity Rules:
1. **Never Cut on Rising Intonation or Incomplete Sentences**:
   - Every clip segment MUST end after the terminal punctuation (period, exclamation, full laugh release).
   - If a creator says *"Watch what happens when I press this—"* cutting here is an amateur mistake that frustrates viewers. The segment MUST include the button press and the reaction.
2. **Acoustic Breath Padding**:
   - Always retain **+0.35s to +0.60s** of room tone/tail reaction after the final word so the audio decays naturally.
3. **J-Cuts and L-Cuts (Audio Overlapping)**:
   - **L-Cut**: The creator’s laughter or sentence finishes *over* the opening frames of the next scene.
   - **J-Cut**: The audio/sound effect of the next scene starts 0.3s *before* the video cuts.
4. **Crossfading and Transition Sound Bridges**:
   - In automated FFmpeg assembly, apply `acrossfade=d=0.30:c1=tri:c2=tri` or micro head/tail fades (`afade=t=in:d=0.08` and `afade=t=out:d=0.12`).
   - Layer subtle whoosh/impact sound effects across scene cut boundaries to mask acoustic room shifts.

---

## 3. Visual Rhythm & The 3-Second Retention Engine

Viewers leave when the visual state is static. Live Speedy maintains 70%+ retention by continuously modulating visual stimuli:

### A. Dynamic Punch-In Reaction Zooms
- **Standard Punch-In**: 1.15x to 1.22x zoom centered on the facecam or action.
- **Trigger**: Audio energy volume spikes (> 1.8x baseline RMS), laughter, shouting, or comedic punchlines.
- **Duration**: 2.5 to 6.0 seconds, then snapping back to wide framing.
```bash
# FFmpeg 1.18x Center Reaction Punch-in
ffmpeg -i in.mp4 -vf "scale=1.18*iw:1.18*ih,crop=iw/1.18:ih/1.18:(1.18*iw-iw)/2:(1.18*ih-ih)/2" -c:a copy punch.mp4
```

### B. Combat / Rapid Argument Pacing
- Fast alternating framing every 4–8 seconds (zoomed on speaker A, wide on both, zoomed on speaker B).

### C. Glassmorphic Chapter Cards & HUD Alerts
- Semi-transparent, sleek dark lower-third cards introducing each Act for 4.5 seconds.
- Top status warning badges during high-intensity moments.

---

## 4. Viral Shorts & Clipping Standards (59.0s to 150.0s)

For vertical Shorts and Reels extracted from streams:
1. **Duration Strict Enforcing**:
   - **Minimum**: `59.0s` (clips shorter than 59s fail retention monetization and narrative depth).
   - **Maximum**: `150.0s` (2.5 minutes).
2. **The 3-Second Hook**:
   - The opening sentence must immediately state the premise or pose a question.
3. **Zero-Cliffhanger & Payoff Verification**:
   - Anticipation phrases ("Look at this", "Wait for it", "He doesn't know") receive a severe penalty (-75 pts) if placed within the last 4 seconds of a clip.
   - Always extend the boundary until the reaction / consequence is fully shown.
4. **9:16 Smart Auto-Framing**:
   - Center crop or dynamic face-tracking blur background for 1080x1920 mobile screens.

---

## 5. Professional YouTube Audio Mastering

Stream audio is notorious for wide dynamic range: quiet whispering followed by ear-destroying screaming.

### A. EBU R128 Loudness Normalization (-14 LUFS)
YouTube normalizes longform uploads to **-14 LUFS** with a maximum true peak of **-1.5 dBTP**.
```bash
# EBU R128 Loudness Filter
-af "loudnorm=I=-14:TP=-1.5:LRA=11"
```

### B. Sidechain Background Music Ducking
Background music must NEVER compete with the creator's voice.
- Music volume: Baseline 25–32%.
- Sidechain ducking: When creator speaks, music automatically ducks by **-12dB to -15dB** with a 20ms attack and 350ms release.
```bash
# FFmpeg Sidechain Compression
[music][dialogue]sidechaincompress=threshold=0.06:ratio=5:attack=20:release=350[ducked_music];
[dialogue][ducked_music]amix=inputs=2:duration=first:dropout_transition=2[mastered_audio]
```

---

## 6. Pre-Publish Quality Assurance Checklist

Before finalizing any longform video or short clip:
- [ ] **No mid-word cuts**: Did every segment end on a completed word and vocal decay?
- [ ] **Audio smoothness**: Is there an audio crossfade or micro-fade between all cut points? Zero audio pops.
- [ ] **Runtime compliance**: Longform feature strictly 420s–540s (7–9m); Shorts strictly 59.0s–150.0s.
- [ ] **Hook potency**: Does Act 0 / the first 3 seconds grab immediate attention?
- [ ] **Mastering**: Audio mastered to -14 LUFS, music ducked cleanly under dialogue.
- [ ] **Context-Aware Metadata**: Title, description, and chapter timestamps accurately reflect the video content without hardcoded placeholders.
