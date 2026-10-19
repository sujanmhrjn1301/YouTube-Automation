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
from src.models import FullTranscription, ViralClip, ClipCut, LLMProvider


VIRAL_DETECTION_SYSTEM_PROMPT = """
You are an elite YouTube Shorts Strategist, Viral Growth Consultant, and Video Editor.
Your job is to analyze video transcripts and extract the single most viral, high-retention segment (30 to 55 seconds long) optimized for the YouTube Shorts algorithm.

ALGORITHMIC VIRAL CRITERIA:
1. Hook Score (1-10): The first 3 seconds (seconds 0-3) must immediately grab curiosity, create an open loop, make a bold claim, or state an intriguing question. No generic pleasantries ("welcome back", "today we are", "let me tell you").
2. Standalone Coherence: The segment MUST be a complete, self-contained thought or story. It must NOT start with dangling pronouns without context, and must NOT cut off mid-sentence.
3. Retention Arc: Strong punchy opening -> compelling elaboration/tension/humor -> satisfying payoff or conclusion suitable for an infinite loop.
4. Target Length: Total runtime MUST be strictly between 45.0 and 59.0 seconds. Under NO circumstances return less than 45.0 seconds.
5. High Shareability: High emotional payoff, counter-intuitive insight, comedy, life hack, or controversial debate point.

LOCAL CONDENSATION / JUMP-CUTS:
If the moment has a great hook followed by slow chatter, dead air, or silent grinding before the climax, you may condense it into 2 to 3 tight, consecutive sub-cuts within a local 90-180 second window to skip boring filler!
Each cut must be at least 8.0 seconds.
The SUM of all cut durations (sum(end_time - start_time)) MUST be strictly between 45.0 and 59.0 seconds.
If the segment is already fast-paced without filler, you can output 1 single cut between 45.0 and 59.0 seconds.

You MUST respond strictly with a valid JSON object matching this schema:
{
  "start_time": float,
  "end_time": float,
  "cuts": [
    {"start_time": float, "end_time": float, "role": "hook"}
  ],
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

    def detect_viral_moment(
        self,
        transcription: FullTranscription,
        allow_multi_cut: bool = True,
        allow_extended_duration: bool = False,
    ) -> ViralClip:
        """
        Analyze transcript with LLM to select the optimal viral clip.
        When allow_multi_cut=False (e.g. stream mode), selects a single continuous uninterrupted moment.
        When allow_extended_duration=True (e.g. stream mode), autonomously decides if moment needs up to 120s.
        """
        log_stage(3, "Viral Moment Detection", f"LLM Provider: {self.provider.upper()}")

        formatted_transcript = self._format_chunked_transcript(transcription)

        # Compute actual absolute bounds of the transcript
        if transcription.segments:
            min_timestamp = min(seg.start for seg in transcription.segments)
            max_timestamp = max(seg.end for seg in transcription.segments)
        else:
            min_timestamp = 0.0
            max_timestamp = transcription.duration

        transcript_duration = max(transcription.duration, max_timestamp - min_timestamp)
        max_limit = max_timestamp

        if allow_extended_duration:
            cut_instruction = (
                "Select a single continuous, uninterrupted viral moment. "
                "TARGET DURATION: If the peak moment naturally concludes within 45.0 to 60.0 seconds, keep it under 60.0 seconds. "
                "CRITICAL EXTENSION RULE: If the full narrative arc, punchline, action climax, or payoff CANNOT fit within 60 seconds, "
                "you are authorized to AUTONOMOUSLY EXTEND the continuous moment up to 120.0 seconds maximum so the scene finishes naturally. "
                "Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            )
            duration_rule = (
                "Total Duration MUST be between 45.0 and 120.0 seconds. "
                "(Aim for 45-60s for standard moments; extend up to 120.0s if needed to complete the full storyline or climax)."
            )
            max_clip_duration = 120.0
        elif allow_multi_cut:
            cut_instruction = "Select the most viral segment or condensed sequence strictly between 45.0 and 59.0 seconds."
            duration_rule = "Total Duration MUST be strictly between 45.0 and 59.0 seconds. Do not return anything under 45 seconds."
            max_clip_duration = 59.0
        else:
            cut_instruction = "Select a single continuous, uninterrupted viral moment strictly between 45.0 and 59.0 seconds. Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            duration_rule = "Total Duration MUST be strictly between 45.0 and 59.0 seconds. Do not return anything under 45 seconds."
            max_clip_duration = 59.0

        user_prompt = f"""
Analyze the following timestamped video transcript (Time Range: {min_timestamp:.1f}s to {max_timestamp:.1f}s, Duration: {transcript_duration:.1f} seconds).
{cut_instruction}

CRITICAL: All timestamps (start_time, end_time, and cuts) MUST use the exact absolute timestamps shown in brackets in the transcript (between {min_timestamp:.1f}s and {max_timestamp:.1f}s).
Ensure start_time and end_time align with clean sentence starts and stops in the transcript.
{duration_rule}

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
        raw_cuts = parsed_json.get("cuts", [])

        snapped_cuts: List[ClipCut] = []
        if allow_multi_cut and isinstance(raw_cuts, list) and len(raw_cuts) > 1:
            snapped_cuts = self.snap_cuts_sequence(raw_cuts, transcription, max_limit)
            if snapped_cuts:
                snapped_start = snapped_cuts[0].start_time
                snapped_end = snapped_cuts[-1].end_time
                total_dur = sum(c.end_time - c.start_time for c in snapped_cuts)
                log_info(
                    "VIRAL_DETECTOR",
                    f"Multi-Cut Condensation: {len(snapped_cuts)} cuts spanning [{snapped_start:.1f}s -> {snapped_end:.1f}s] (Total Shorts Duration: {total_dur:.1f}s)",
                )
            else:
                snapped_start, snapped_end = self.snap_to_word_boundaries(raw_start, raw_end, transcription, max_limit, max_duration=max_clip_duration)
                snapped_cuts = [ClipCut(start_time=snapped_start, end_time=snapped_end, role="clip")]
        else:
            snapped_start, snapped_end = self.snap_to_word_boundaries(raw_start, raw_end, transcription, max_limit, max_duration=max_clip_duration)
            snapped_cuts = [ClipCut(start_time=snapped_start, end_time=snapped_end, role="clip")]

        viral_clip = ViralClip(
            start_time=snapped_start,
            end_time=snapped_end,
            cuts=snapped_cuts,
            hook_title=str(parsed_json.get("hook_title", "Unbelievable Viral Moment #Shorts")),
            description=str(parsed_json.get("description", "Watch this incredible moment! #Shorts")),
            tags=list(parsed_json.get("tags", ["Shorts", "Viral", "Trending"])),
            viral_reasoning=str(parsed_json.get("viral_reasoning", "Engaging hook with self-contained narrative.")),
            hook_score=int(parsed_json.get("hook_score", 8)),
        )

        log_viral_moment(viral_clip.model_dump())
        return viral_clip

    def snap_single_cut(
        self,
        raw_start: float,
        raw_end: float,
        all_words: List[Any],
        total_duration: float,
        trim_fillers: bool = False,
    ) -> Tuple[float, float]:
        """Snaps a single sub-cut to exact word boundaries."""
        if raw_end <= raw_start:
            raw_end = min(total_duration, raw_start + 25.0)

        if not all_words:
            return round(max(0.0, raw_start), 2), round(min(total_duration, max(raw_start + 4.0, raw_end)), 2)

        start_cands = [w for w in all_words if abs(w.start - raw_start) <= 3.5]
        start_word = min(start_cands, key=lambda w: abs(w.start - raw_start)) if start_cands else min(all_words, key=lambda w: abs(w.start - raw_start))
        start_idx = all_words.index(start_word)

        if trim_fillers:
            filler_words = {"um", "uh", "uhm", "er", "ah", "like", "so", "actually", "basically"}
            while start_idx < len(all_words) - 1:
                clean_tok = all_words[start_idx].word.strip().lower().rstrip(".,!?")
                if clean_tok in filler_words and (all_words[start_idx + 1].start - all_words[start_idx].end) < 1.2:
                    start_idx += 1
                else:
                    break

        s_time = all_words[start_idx].start

        end_cands = [w for w in all_words[start_idx:] if abs(w.end - raw_end) <= 3.5]
        if end_cands:
            def score_cand(w: Any) -> float:
                score = -abs(w.end - raw_end)
                if any(w.word.strip().endswith(p) for p in [".", "!", "?"]):
                    score += 8.0
                return score
            end_word = max(end_cands, key=score_cand)
            e_time = end_word.end
        else:
            e_time = min(total_duration, max(s_time + 4.0, raw_end))

        if (e_time - s_time) < 3.0:
            e_time = min(total_duration, s_time + 4.0)

        return round(s_time, 2), round(e_time, 2)

    def snap_cuts_sequence(
        self,
        raw_cuts: List[Dict[str, Any]],
        transcription: FullTranscription,
        total_duration: float,
    ) -> List[ClipCut]:
        """Snaps each cut in a multi-cut sequence and validates overall duration."""
        all_words = [w for seg in transcription.segments for w in seg.words]
        snapped_list: List[ClipCut] = []

        for idx, cut in enumerate(raw_cuts):
            rs = float(cut.get("start_time", 0.0))
            re = float(cut.get("end_time", rs + 10.0))
            if re <= rs:
                re = min(total_duration, rs + 25.0)
            role = str(cut.get("role", f"cut_{idx + 1}"))
            ss, se = self.snap_single_cut(rs, re, all_words, total_duration, trim_fillers=(idx == 0))
            if se > ss:
                snapped_list.append(ClipCut(start_time=ss, end_time=se, role=role))

        if not snapped_list:
            return []

        total_dur = sum(c.end_time - c.start_time for c in snapped_list)
        if total_dur < 45.0:
            needed = 45.0 - total_dur
            last_cut = snapped_list[-1]
            target_end = min(total_duration, last_cut.end_time + needed)
            cands = [w for w in all_words if w.end >= target_end and w.end <= min(total_duration, target_end + 12.0)]
            if cands:
                best = max(cands, key=lambda w: (15.0 if any(w.word.strip().endswith(p) for p in [".", "!", "?"]) else 0.0) - abs(w.end - target_end))
                last_cut.end_time = best.end
            else:
                last_cut.end_time = round(target_end, 2)
            total_dur = sum(c.end_time - c.start_time for c in snapped_list)

        if total_dur > 59.0:
            excess = total_dur - 58.0
            last_cut = snapped_list[-1]
            new_last_end = max(last_cut.start_time + 8.0, last_cut.end_time - excess)
            snapped_list[-1].end_time = round(new_last_end, 2)

        return snapped_list

    def snap_to_word_boundaries(
        self,
        raw_start: float,
        raw_end: float,
        transcription: FullTranscription,
        total_duration: float,
        max_duration: float = 59.0,
    ) -> Tuple[float, float]:
        """
        Refines raw LLM timestamps by snapping to exact word boundaries from Whisper:
        1. Trims leading filler words ("um", "uh", "like", "you know", "so") so the clip hooks immediately.
        2. Snaps clip start to the onset of the first strong spoken word.
        3. Snaps clip end to the end of the sentence or nearest natural pause, avoiding mid-sentence cuts.
        4. Guarantees target duration strictly between 45.0s and max_duration (up to 120.0s).
        """
        all_words: List[Any] = []
        for seg in transcription.segments:
            all_words.extend(seg.words)

        if not all_words:
            s = max(0.0, raw_start)
            e = min(total_duration, max(s + 45.0, min(raw_end, s + (max_duration - 1.0))))
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

        # 2. Find the best ending word near target duration (between 45.0s and max_duration)
        raw_len = max(45.0, raw_end - raw_start)
        target_len = min(max_duration - 1.0, raw_len)
        min_end_time = snapped_start + 45.0
        max_end_time = min(total_duration, snapped_start + max_duration)

        end_candidates = [
            w for w in all_words[start_idx:]
            if w.end >= min_end_time and w.end <= max_end_time
        ]

        if not end_candidates:
            valid_words = [w for w in all_words[start_idx:] if w.end <= total_duration]
            if valid_words:
                end_word = min(valid_words, key=lambda w: abs(w.end - (snapped_start + target_len)))
                snapped_end = end_word.end
            else:
                snapped_end = min(total_duration, snapped_start + min(48.0, max_duration))
        else:
            def score_end_word(w: Any) -> float:
                score = -abs(w.end - (snapped_start + target_len))
                text = w.word.strip()
                if any(text.endswith(p) for p in [".", "!", "?"]):
                    score += 15.0
                return score

            best_end_word = max(end_candidates, key=score_end_word)
            snapped_end = best_end_word.end

        # Final duration bounds verification
        final_dur = snapped_end - snapped_start
        if final_dur < 45.0:
            snapped_end = min(total_duration, snapped_start + min(48.0, max_duration))
        elif final_dur > max_duration:
            snapped_end = min(total_duration, snapped_start + (max_duration - 0.5))

        return round(max(0.0, snapped_start), 2), round(min(total_duration, snapped_end), 2)
