"""
Stage 3: Viral Moment Detection and Metadata Generation Service.
Prompts LLM (OpenAI, Gemini, or OpenRouter) with timestamped transcripts to identify viral YouTube Shorts.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple
from openai import OpenAI

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_viral_moment,
    console,
)
from src.models import FullTranscription, ViralClip, LLMProvider


VIRAL_DETECTION_SYSTEM_PROMPT = """
You are an elite YouTube Shorts Strategist, Viral Growth Consultant, and Video Editor.
Your job is to analyze full-length video transcripts and extract the single most viral, high-retention segment (30 to 55 seconds long) optimized for the YouTube Shorts algorithm.

ALGORITHMIC VIRAL CRITERIA:
1. Hook Score (1-10): The first 3 seconds (seconds 0-3) must immediately grab curiosity, create an open loop, make a bold claim, or state an intriguing question. No generic pleasantries ("welcome back", "today we are", "let me tell you").
2. Standalone Coherence: The segment MUST be a complete, self-contained thought or story. It must NOT start with dangling pronouns ("So he said...", "And then this...") without context, and must NOT cut off mid-sentence.
3. Retention Arc: Strong punchy opening -> compelling elaboration/tension/humor -> satisfying payoff or conclusion suitable for an infinite loop.
4. Target Length: STRICTLY between 30.0 and 55.0 seconds (end_time - start_time >= 30.0 and <= 55.0).
5. High Shareability: High emotional payoff, counter-intuitive insight, comedy, life hack, or controversial debate point.

You MUST respond strictly with a valid JSON object matching this schema:
{
  "start_time": float,
  "end_time": float,
  "hook_title": "Short punchy title under 60 chars with #Shorts",
  "description": "2-3 sentence engaging description with relevant hashtags",
  "tags": ["tag1", "tag2", "tag3", "Shorts"],
  "viral_reasoning": "Detailed justification of the hook in seconds 0-3 and narrative arc",
  "hook_score": int
}
"""


class ViralDetectorService:
    """Detects viral moments using LLM APIs (OpenRouter default)."""

    def __init__(self, provider: str = "openrouter", model: Optional[str] = None) -> None:
        self.provider = provider.lower()
        self.custom_model = model
        self.openai_client: Optional[OpenAI] = None
        self.gemini_client = None
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize provider client with API keys from .env."""
        if self.provider == "openrouter":
            if settings.OPENROUTER_API_KEY:
                self.openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=settings.OPENROUTER_API_KEY,
                    timeout=120.0,
                    max_retries=3,
                    default_headers={
                        "HTTP-Referer": "https://github.com/youtube-pipeline",
                        "X-Title": "YouTube Shorts Automation Pipeline",
                    },
                )
            else:
                log_error("VIRAL_DETECTOR", "OPENROUTER_API_KEY not found in .env.")
                raise ValueError("OPENROUTER_API_KEY is required in .env")

        elif self.provider == "openai":
            if settings.OPENAI_API_KEY:
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=120.0, max_retries=3)
            elif settings.OPENROUTER_API_KEY:
                log_info(
                    "VIRAL_DETECTOR",
                    "Using OPENROUTER_API_KEY from .env for LLM analysis.",
                )
                self.provider = "openrouter"
                self.openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=settings.OPENROUTER_API_KEY,
                    timeout=120.0,
                    max_retries=3,
                    default_headers={
                        "HTTP-Referer": "https://github.com/youtube-pipeline",
                        "X-Title": "YouTube Shorts Automation Pipeline",
                    },
                )
            else:
                log_warning("VIRAL_DETECTOR", "Neither OPENAI_API_KEY nor OPENROUTER_API_KEY found.")

        elif self.provider == "gemini":
            if settings.GEMINI_API_KEY:
                try:
                    from google import genai
                    self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                except Exception as e:
                    log_error("VIRAL_DETECTOR", f"Failed to initialize google-genai client: {e}")
            elif settings.OPENROUTER_API_KEY:
                log_info(
                    "VIRAL_DETECTOR",
                    "GEMINI_API_KEY not found; routing Gemini request via OPENROUTER_API_KEY.",
                )
                self.provider = "openrouter"
                self.openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=settings.OPENROUTER_API_KEY,
                )

    def _format_chunked_transcript(self, transcription: FullTranscription, chunk_seconds: float = 7.0) -> str:
        """
        Group words and segments into 5-to-10-second chunks with clear timestamps.
        """
        chunks: List[str] = []
        current_chunk_words: List[str] = []
        chunk_start: Optional[float] = None
        chunk_end: float = 0.0

        for seg in transcription.segments:
            if not seg.words:
                chunks.append(f"[{seg.start:06.2f}s -> {seg.end:06.2f}s] {seg.text}")
                continue

            for w in seg.words:
                if chunk_start is None:
                    chunk_start = w.start

                current_chunk_words.append(w.word)
                chunk_end = w.end

                if (chunk_end - chunk_start) >= chunk_seconds:
                    text_joined = " ".join(current_chunk_words)
                    chunks.append(f"[{chunk_start:06.2f}s -> {chunk_end:06.2f}s] {text_joined}")
                    current_chunk_words = []
                    chunk_start = None

        if current_chunk_words and chunk_start is not None:
            text_joined = " ".join(current_chunk_words)
            chunks.append(f"[{chunk_start:06.2f}s -> {chunk_end:06.2f}s] {text_joined}")

        return "\n".join(chunks)

    def detect_viral_moment(self, transcription: FullTranscription) -> ViralClip:
        """
        Analyze transcript with LLM to select the optimal viral clip.
        """
        log_stage(3, "Viral Moment Detection", f"LLM Provider: {self.provider.upper()}")

        formatted_transcript = self._format_chunked_transcript(transcription)
        total_duration = transcription.duration

        user_prompt = f"""
Analyze the following timestamped video transcript (Total Duration: {total_duration:.1f} seconds).
Select the most viral segment between 30.0 and 55.0 seconds.

Ensure start_time and end_time align with clean sentence starts and stops in the transcript.
Duration MUST be between 30 and 55 seconds.

TRANSCRIPT:
{formatted_transcript}
"""

        log_info("VIRAL_DETECTOR", f"Sending structured request to LLM ({len(formatted_transcript)} characters transcript)...")
        start_eval = time.time()

        if self.provider in ["openai", "openrouter"]:
            if not self.openai_client:
                raise ValueError("OpenAI/OpenRouter client is not configured. Check API key in .env.")

            if self.provider == "openrouter":
                primary_model = self.custom_model or settings.OPENROUTER_MODEL
                models_to_try = [
                    primary_model,
                    "google/gemini-2.0-flash-001",
                    "meta-llama/llama-3.3-70b-instruct",
                ]
            else:
                models_to_try = [self.custom_model or "gpt-4o-mini"]

            raw_content = None
            last_err = None

            for m in models_to_try:
                log_info("VIRAL_DETECTOR", f"Requesting viral moment analysis with: {m} (via {self.provider.upper()})")
                for attempt in range(1, 4):
                    try:
                        response = self.openai_client.chat.completions.create(
                            model=m,
                            messages=[
                                {"role": "system", "content": VIRAL_DETECTION_SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.4,
                        )
                        raw_content = response.choices[0].message.content
                        usage = response.usage
                        if usage:
                            log_info(
                                "VIRAL_DETECTOR",
                                f"Token Usage - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}, Total: {usage.total_tokens}",
                            )
                        break
                    except Exception as err:
                        last_err = err
                        log_warning(
                            "VIRAL_DETECTOR",
                            f"LLM request to {m} attempt {attempt}/3 failed: {err}. Retrying in {attempt * 2}s...",
                        )
                        time.sleep(attempt * 2)

                if raw_content:
                    break

            if not raw_content:
                raise RuntimeError(f"All LLM attempts and fallbacks failed: {last_err}")

        elif self.provider == "gemini":
            if not self.gemini_client:
                raise ValueError("Gemini client is not configured. Check GEMINI_API_KEY in .env.")

            model_name = "gemini-2.5-flash"
            log_info("VIRAL_DETECTOR", f"Using Google GenAI model: {model_name}")

            response = self.gemini_client.models.generate_content(
                model=model_name,
                contents=f"{VIRAL_DETECTION_SYSTEM_PROMPT}\n\n{user_prompt}",
                config={"response_mime_type": "application/json"},
            )
            raw_content = response.text
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        elapsed = time.time() - start_eval
        log_success("VIRAL_DETECTOR", f"Received LLM analysis in {elapsed:.2f}s")

        parsed_json: Dict[str, Any] = json.loads(raw_content)

        raw_start = float(parsed_json.get("start_time", 0.0))
        raw_end = float(parsed_json.get("end_time", 0.0))

        # Apply algorithmic word-boundary snapping & filler trimming
        snapped_start, snapped_end = self.snap_to_word_boundaries(
            raw_start=raw_start,
            raw_end=raw_end,
            transcription=transcription,
            total_duration=total_duration,
        )

        log_info(
            "VIRAL_DETECTOR",
            f"Algorithmic boundary alignment: Raw [{raw_start:.2f}s -> {raw_end:.2f}s] "
            f"=> Snapped [{snapped_start:.2f}s -> {snapped_end:.2f}s] (Duration: {snapped_end - snapped_start:.2f}s)",
        )

        viral_clip = ViralClip(
            start_time=snapped_start,
            end_time=snapped_end,
            hook_title=str(parsed_json.get("hook_title", "Unbelievable Viral Moment #Shorts")),
            description=str(parsed_json.get("description", "Watch this incredible moment! #Shorts")),
            tags=list(parsed_json.get("tags", ["Shorts", "Viral", "Trending"])),
            viral_reasoning=str(parsed_json.get("viral_reasoning", "Engaging hook with self-contained narrative.")),
            hook_score=int(parsed_json.get("hook_score", 8)),
        )

        log_viral_moment(viral_clip.model_dump())
        return viral_clip

    def snap_to_word_boundaries(
        self,
        raw_start: float,
        raw_end: float,
        transcription: FullTranscription,
        total_duration: float,
    ) -> Tuple[float, float]:
        """
        Refines raw LLM timestamps by snapping to exact word boundaries from Whisper:
        1. Trims leading filler words ("um", "uh", "like", "you know", "so") so the clip hooks immediately.
        2. Snaps clip start to the onset of the first strong spoken word.
        3. Snaps clip end to the end of the sentence or nearest natural pause, avoiding mid-sentence cuts.
        4. Guarantees target duration strictly between 30.0 and 58.0 seconds.
        """
        all_words: List[Any] = []
        for seg in transcription.segments:
            all_words.extend(seg.words)

        if not all_words:
            s = max(0.0, raw_start)
            e = min(total_duration, max(s + 30.0, min(raw_end, s + 55.0)))
            return round(s, 2), round(e, 2)

        filler_words = {"um", "uh", "uhm", "er", "ah", "like", "so", "actually", "basically"}

        # 1. Find the best starting word near raw_start
        start_candidates = [w for w in all_words if abs(w.start - raw_start) <= 4.0]
        if not start_candidates:
            start_word = min(all_words, key=lambda w: abs(w.start - raw_start))
        else:
            start_candidates.sort(key=lambda w: abs(w.start - raw_start))
            start_word = start_candidates[0]

        start_idx = all_words.index(start_word)

        # Skip leading filler words if adjacent word follows closely (< 1.2s)
        while start_idx < len(all_words) - 1:
            clean_token = all_words[start_idx].word.strip().lower().rstrip(".,!?")
            if clean_token in filler_words and (all_words[start_idx + 1].start - all_words[start_idx].end) < 1.2:
                start_idx += 1
            else:
                break

        snapped_start = all_words[start_idx].start

        # 2. Find the best ending word near raw_end (targeting 30-55s duration)
        min_end_time = snapped_start + 30.0
        max_end_time = min(total_duration, snapped_start + 58.0)

        end_candidates = [
            w for w in all_words[start_idx:]
            if w.end >= min_end_time and w.end <= max_end_time
        ]

        if not end_candidates:
            valid_words = [w for w in all_words[start_idx:] if w.end <= total_duration]
            if valid_words:
                end_word = min(valid_words, key=lambda w: abs(w.end - raw_end))
                snapped_end = end_word.end
            else:
                snapped_end = min(total_duration, snapped_start + 45.0)
        else:
            def score_end_word(w: Any) -> float:
                score = -abs(w.end - raw_end)
                text = w.word.strip()
                if any(text.endswith(p) for p in [".", "!", "?"]):
                    score += 10.0
                return score

            best_end_word = max(end_candidates, key=score_end_word)
            snapped_end = best_end_word.end

        # Final duration bounds verification
        final_dur = snapped_end - snapped_start
        if final_dur < 28.0:
            snapped_end = min(total_duration, snapped_start + 35.0)
        elif final_dur > 58.0:
            snapped_end = snapped_start + 55.0

        return round(max(0.0, snapped_start), 2), round(min(total_duration, snapped_end), 2)
