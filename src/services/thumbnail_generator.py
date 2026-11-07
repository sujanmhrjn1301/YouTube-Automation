"""
Service for AI-generated YouTube thumbnails (1280x720, 16:9) and video keyframe extraction.
Specifically tailored for Longform Feature videos and Viral Montages.
"""

import json
import os
import random
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import resolve_ffmpeg_path, settings
from src.console import log_error, log_info, log_success, log_warning


class ThumbnailGeneratorService:
    """Generates high-CTR 1280x720 YouTube thumbnails using AI (FLUX) or video frame capture."""

    def __init__(self) -> None:
        self.output_dir: Path = settings.OUTPUT_DIR / "thumbnails"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_exe = resolve_ffmpeg_path()

    def enhance_thumbnail_prompt(self, title: str, style: str = "viral") -> str:
        """
        Synthesize a high-CTR visual image prompt from video title and style.
        Uses OpenRouter if configured, otherwise uses expert prompt crafting heuristics.
        """
        clean_title = re.sub(r"[\[\(].*?[\]\)]", "", title).strip()

        # Style descriptors
        style_hints = {
            "viral": "extreme facial expression, dramatic hyper-saturated cinematic lighting, shock and hype, YouTube thumbnail aesthetic, intense depth of field",
            "dark": "spooky dark eerie haunted atmosphere, glowing flashlights, terrifying shadows, cinematic horror movie lighting, volumetric fog",
            "gaming": "hyper-vibrant neon gaming studio, dynamic action angle, vivid saturated colors, energetic motion, crisp 8k render",
            "cinematic": "masterpiece cinematic frame, anamorphic lens flare, moody color grading, epic movie still, dramatic composition",
        }
        chosen_style = style_hints.get(style, style_hints["viral"])

        # Try OpenRouter if API key is present
        if settings.OPENROUTER_API_KEY:
            try:
                headers = {
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/sujanmhrjn1301/YouTube-Automation",
                }
                system_prompt = (
                    "You are an elite YouTube thumbnail visual designer for top creators (MrBeast, IShowSpeed). "
                    "Write a single, highly-detailed 25-word visual image generation prompt describing a cinematic, eye-catching 16:9 YouTube thumbnail. "
                    "Do NOT include words, text, logos, or letters inside the image. Focus purely on character expression, action, lighting, and intense background atmosphere."
                )
                payload = {
                    "model": settings.OPENROUTER_MODEL or "openai/gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Video Title: '{clean_title}'. Style: {chosen_style}."},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 120,
                }
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"].strip()
                    # Clean any quotes or prefixes
                    content = re.sub(r'^(Prompt:|"|\')|("|\')$', "", content).strip()
                    if content and len(content) > 15:
                        return f"{content}, 16:9 aspect ratio, 8k resolution, ultra-detailed"
            except Exception as e:
                log_warning("THUMBNAIL", f"OpenRouter prompt synthesis note: {e}")

        # Fallback heuristic prompt template
        return (
            f"Cinematic high-contrast YouTube thumbnail for '{clean_title}', "
            f"{chosen_style}, dramatic lighting, hyper-detailed, expressive character, 16:9 ratio, ultra-hd 8k"
        )

    def generate_ai_thumbnail(
        self,
        title: str,
        custom_prompt: Optional[str] = None,
        style: str = "viral",
        short_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate a 1280x720 16:9 thumbnail using Pollinations FLUX engine.
        Returns metadata with saved file path and relative URL.
        """
        prompt = custom_prompt.strip() if custom_prompt and custom_prompt.strip() else self.enhance_thumbnail_prompt(title, style)
        log_info("THUMBNAIL", f"🎨 Generating AI thumbnail: '{prompt[:70]}...'")

        for attempt in range(3):
            try:
                seed = random.randint(10000, 999999)
                url = (
                    f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                    f"?width=1280&height=720&model=flux&nologo=true&seed={seed}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=35) as resp:
                    data = resp.read()
                    if len(data) >= 5000:
                        with open(out_path, "wb") as f:
                            f.write(data)

                        log_success("THUMBNAIL", f"✅ AI thumbnail saved: {out_path.name} ({len(data) // 1024} KB)")
                        return {
                            "success": True,
                            "thumbnail_path": str(out_path.resolve()),
                            "thumbnail_url": f"/api/thumbnails/{out_filename}",
                            "filename": out_filename,
                            "prompt": prompt,
                            "mode": "ai",
                        }
            except Exception as e:
                log_warning("THUMBNAIL", f"Attempt {attempt + 1}/3 note: {e}")
                if attempt < 2:
                    time.sleep(2)

        return {
            "success": False,
            "error": "Thumbnail generation timed out. Please try clicking Generate again or extract a video frame.",
            "prompt": prompt,
        }

    def extract_video_frame(
        self,
        video_path: str,
        timestamp_sec: float = 10.0,
        short_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Extract a pristine 16:9 keyframe from a local video file using FFmpeg.
        """
        vpath = Path(video_path)
        if not vpath.exists():
            return {"success": False, "error": f"Video file not found at {video_path}"}

        ts = int(time.time())
        id_part = f"short_{short_id}_" if short_id else ""
        out_filename = f"frame_{id_part}{ts}.jpg"
        out_path = self.output_dir / out_filename

        cmd = [
            self.ffmpeg_exe,
            "-ss", str(max(0.0, timestamp_sec)),
            "-i", str(vpath),
            "-vframes", "1",
            "-q:v", "2",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            "-y",
            str(out_path),
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if out_path.exists() and out_path.stat().st_size > 1000:
                log_success("THUMBNAIL", f"✅ Keyframe extracted: {out_path.name}")
                return {
                    "success": True,
                    "thumbnail_path": str(out_path.resolve()),
                    "thumbnail_url": f"/api/thumbnails/{out_filename}",
                    "filename": out_filename,
                    "timestamp": timestamp_sec,
                    "mode": "frame",
                }
            else:
                err = res.stderr.decode("utf-8", errors="ignore")[-200:]
                return {"success": False, "error": f"FFmpeg failed to extract frame: {err}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
