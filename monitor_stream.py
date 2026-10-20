"""
Autonomous YouTube Livestream Monitoring & Real-Time Clipping CLI.
Continuously watches for live streams, clips viral moments into 9:16 Shorts with karaoke captions,
and saves them strictly into your dedicated 'livestream-shorts' Supabase bucket.
"""

import sys
import click
from typing import Optional

from src.console import console
from src.services.stream_monitor import StreamMonitorAgent


@click.command(help="Run Autonomous YouTube Livestream Monitoring & Real-Time Clipping Agent.")
@click.option(
    "--url",
    "-u",
    required=True,
    help="Target YouTube Livestream URL (e.g. 'https://www.youtube.com/@Channel/live' or 'https://www.youtube.com/watch?v=...').",
)
@click.option(
    "--chunk-duration",
    "-c",
    default=150,
    show_default=True,
    type=int,
    help="Rolling buffer window in seconds to capture from live stream (e.g. 120-180s).",
)
@click.option(
    "--poll-interval",
    "-p",
    default=45,
    show_default=True,
    type=int,
    help="Seconds to wait between liveness checks or consecutive live buffer extractions.",
)
@click.option(
    "--crop-mode",
    default="blurred_background",
    show_default=True,
    type=click.Choice(["blurred_background", "center_crop", "face_tracking"], case_sensitive=False),
    help="Vertical 9:16 reframing layout style.",
)
@click.option(
    "--bleep-profanity / --no-bleep-profanity",
    default=True,
    show_default=True,
    help="Automatically detect English swear words and censor with 1000Hz bleeps.",
)
@click.option(
    "--auto-upload",
    is_flag=True,
    default=False,
    help="Also publish the generated live Shorts directly to YouTube in addition to Supabase storage.",
)
@click.option(
    "--max-clips",
    default=0,
    show_default=True,
    type=int,
    help="Maximum number of live Shorts to create before stopping (0 = continuous infinite monitoring).",
)
@click.option(
    "--once",
    is_flag=True,
    default=False,
    help="Capture and process 1 single live buffer then exit immediately.",
)
@click.option(
    "--llm-provider",
    default="openrouter",
    show_default=True,
    type=click.Choice(["openrouter", "openai", "gemini"], case_sensitive=False),
    help="LLM provider for viral moment detection.",
)
@click.option(
    "--llm-model",
    default=None,
    help="Custom LLM model identifier (e.g. 'meta-llama/llama-3.3-70b-instruct' or 'gpt-4o-mini').",
)
@click.option(
    "--whisper-model",
    default="base",
    show_default=True,
    type=click.Choice(["tiny", "base", "small", "medium", "large-v3"], case_sensitive=False),
    help="Faster-whisper model size for transcription.",
)
def main(
    url: str,
    chunk_duration: int,
    poll_interval: int,
    crop_mode: str,
    bleep_profanity: bool,
    auto_upload: bool,
    max_clips: int,
    once: bool,
    llm_provider: str,
    llm_model: Optional[str],
    whisper_model: str,
) -> None:
    """Run Autonomous YouTube Livestream Monitoring Agent."""
    effective_max_clips = 1 if once else max_clips

    agent = StreamMonitorAgent(
        target_url=url,
        chunk_duration=chunk_duration,
        poll_interval=poll_interval,
        crop_mode=crop_mode,
        bleep_profanity=bleep_profanity,
        auto_upload=auto_upload,
        max_clips=effective_max_clips,
        llm_provider=llm_provider,
        llm_model=llm_model,
        whisper_model=whisper_model,
    )

    agent.run_autonomous_monitor()


if __name__ == "__main__":
    main()
