# ⚡ YouTube Shorts Pipeline — Command Reference

You only need **3 primary commands** for your day-to-day workflow:

---

### 1. 🎬 Process Any Video into Viral Shorts
Extracts peak moments, reframes to 9:16 vertical, adds animated karaoke captions, censors profanity, and saves to `shorts/standard/`.
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
```
> **Tip:** Add `--auto-upload` to publish directly to YouTube (`@eijishorts`) immediately:
> ```powershell
> python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --auto-upload
> ```

---

### 2. 🔴 Autonomous Livestream Monitoring Agent
Continuously monitors an active YouTube live broadcast, captures rolling peak moments, and uploads strictly into your dedicated **`livestream-shorts`** Supabase bucket (isolated from regular shorts).
```powershell
python monitor_stream.py --url "https://www.youtube.com/@ChannelName/live"
```
> **Tip:** Add `--once` if you only want to grab 1 fresh moment from an active stream and stop:
> ```powershell
> python monitor_stream.py --url "https://www.youtube.com/@ChannelName/live" --once
> ```

---

### 3. 🚀 Publish Queued Shorts from Cloud to YouTube
Picks the next unuploaded Short from your Supabase cloud queue and publishes it to your channel, strictly respecting daily YouTube API quotas.
```powershell
python upload_pending.py
```
> **Tip:** To publish all pending unuploaded Shorts at once:
> ```powershell
> python cli.py --upload-all-pending
> ```

---

### 🛠️ Optional Power Flags & Utilities

| Need | Option / Command | Description |
| :--- | :--- | :--- |
| **Check System Health** | `python cli.py --doctor` | Verifies FFmpeg, Whisper, APIs, Supabase, and GPU |
| **Test YouTube Channel** | `python cli.py --auth-youtube` | Checks channel OAuth token and daily upload quota |
| **Free Up Disk Space** | `python cli.py --clean-cache` | Purges expired audio/video cache files |
| **Extract More Shorts** | `--clips-count 5` | Extracts 5 peak parts instead of default 3 |
| **AI Face Tracking** | `--crop-mode face_tracking` | Dynamic AI face-following crop for talking heads |
| **Run Unit Tests** | `pytest tests/test_pipeline_units.py` | Validates entire pipeline (24/24 tests) |
