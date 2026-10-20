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
Your job is to analyze video transcripts and extract the single most viral, high-retention continuous segment optimized for the YouTube Shorts algorithm.

ALGORITHMIC VIRAL CRITERIA:
1. Hook Score (1-10): The first 3 seconds (seconds 0-3) must immediately grab curiosity, create an open loop, make a bold claim, or state an intriguing question. No generic pleasantries ("welcome back", "today we are", "let me tell you").
2. Standalone Coherence & Speech Integrity (CRITICAL):
   - The segment MUST be a single, complete, self-contained thought or story.
   - ABSOLUTE SENTENCE BOUNDARY RULE: The clip MUST start cleanly at the onset of a complete sentence or strong statement, and MUST conclude cleanly at the completion of a full sentence (marked by '.', '!', or '?').
   - ZERO MID-SENTENCE CUTS: Never, under any circumstances, cut off someone midway while they are speaking or leave a thought dangling. No one watches Shorts that end abruptly mid-sentence!
3. Retention Arc: Strong punchy opening -> compelling elaboration/tension/humor -> satisfying payoff or conclusion suitable for an infinite loop.
4. Target Length: Total runtime should be between 35.0 and 58.0 seconds for standard YouTube Shorts (or up to 120.0s if authorized for live streams).
5. High Shareability: High emotional payoff, counter-intuitive insight, comedy, life hack, or controversial debate point.

Provide a single contiguous start_time and end_time for the viral clip.

You MUST respond strictly with a valid JSON object matching this schema:
{
  "start_time": float,
  "end_time": float,
  "cuts": [
    {"start_time": float, "end_time": float, "role": "content"}
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
                "TARGET DURATION: If the peak moment naturally concludes within 35.0 to 60.0 seconds, keep it under 60.0 seconds. "
                "CRITICAL EXTENSION RULE: If the full narrative arc, punchline, action climax, or payoff CANNOT fit within 60 seconds, "
                "you are authorized to AUTONOMOUSLY EXTEND the continuous moment up to 120.0 seconds maximum so the scene finishes naturally. "
                "CRITICAL SPEECH INTEGRITY: The moment MUST start cleanly at the onset of a sentence and MUST end completely at a sentence finish (. ! ?). "
                "Never cut off someone speaking midway. Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            )
            duration_rule = (
                "Total Duration MUST be between 35.0 and 120.0 seconds. "
                "(Aim for 38-58s for standard moments; extend up to 120.0s if needed to complete the full storyline or climax)."
            )
            max_clip_duration = 120.0
        elif allow_multi_cut:
            cut_instruction = (
                "Select the most viral sequence strictly between 35.0 and 58.0 seconds. "
                "Every cut MUST end cleanly on a completed clause or sentence. Never cut off someone mid-word."
            )
            duration_rule = "Total Duration MUST be strictly between 35.0 and 58.0 seconds."
            max_clip_duration = 58.5
        else:
            cut_instruction = (
                "Select a single continuous, uninterrupted viral moment strictly between 35.0 and 58.0 seconds. "
                "CRITICAL: The moment MUST start cleanly at the beginning of a sentence and MUST end completely at a sentence finish (. ! ?). "
                "Under NO circumstances cut off someone who is speaking midway or leave a thought dangling. "
                "Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            )
            duration_rule = "Total Duration MUST be strictly between 35.0 and 58.0 seconds."
            max_clip_duration = 58.5

        user_prompt = f"""
Analyze the following timestamped video transcript (Time Range: {min_timestamp:.1f}s to {max_timestamp:.1f}s, Duration: {transcript_duration:.1f} seconds).
{cut_instruction}

CRITICAL: All timestamps (start_time and end_time) MUST use the exact absolute timestamps shown in brackets in the transcript (between {min_timestamp:.1f}s and {max_timestamp:.1f}s).
Ensure start_time aligns with a clean sentence start and end_time aligns with a completed sentence ending (. ! ?) in the transcript.
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
        """Snaps a single sub-cut to clean sentence or phrase boundaries."""
        if raw_end <= raw_start:
            raw_end = min(total_duration, raw_start + 25.0)

        if not all_words:
            return round(max(0.0, raw_start), 2), round(min(total_duration, max(raw_start + 4.0, raw_end)), 2)

        filler_words = {"um", "uh", "uhm", "er", "ah", "like", "so", "actually", "basically"}
        dangling_words = {
            "and", "but", "or", "because", "so", "then", "that", "which",
            "with", "if", "when", "to", "of", "in", "for", "the", "a", "an",
        }
        sentence_enders = {".", "!", "?"}
        clause_enders = {",", ";", ":", "-", "—"}

        # 1. Snap start
        start_cands = [w for w in all_words if abs(w.start - raw_start) <= 3.5]
        start_word = min(start_cands, key=lambda w: abs(w.start - raw_start)) if start_cands else min(all_words, key=lambda w: abs(w.start - raw_start))
        start_idx = all_words.index(start_word)

        if trim_fillers:
            while start_idx < len(all_words) - 1:
                clean_tok = all_words[start_idx].word.strip().lower().rstrip(".,!?;:-")
                if clean_tok in filler_words and (all_words[start_idx + 1].start - all_words[start_idx].end) < 1.2:
                    start_idx += 1
                else:
                    break

        s_time = all_words[start_idx].start

        # 2. Snap end - prioritize punctuation and pauses, avoid dangling conjunctions
        end_cands = [
            (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
            if abs(w.end - raw_end) <= 4.0
        ]
        if end_cands:
            def score_cand(item: Tuple[int, Any]) -> float:
                idx, w = item
                text = w.word.strip()
                clean_tok = text.lower().rstrip(".,!?;:-")
                dist = abs(w.end - raw_end)
                score = -dist * 2.0

                if any(text.endswith(p) for p in sentence_enders):
                    score += 40.0
                elif any(text.endswith(p) for p in clause_enders):
                    score += 15.0

                if idx < len(all_words) - 1:
                    pause = all_words[idx + 1].start - w.end
                    if pause >= 0.4:
                        score += 25.0
                else:
                    score += 30.0

                if clean_tok in dangling_words:
                    score -= 40.0

                return score

            best_idx, end_word = max(end_cands, key=score_cand)
            end_ts = end_word.end

            # Natural audio release padding
            if best_idx < len(all_words) - 1:
                padding = min(0.18, max(0.0, all_words[best_idx + 1].start - end_ts - 0.03))
            else:
                padding = min(0.18, max(0.0, total_duration - end_ts))
            e_time = end_ts + padding
        else:
            e_time = min(total_duration, max(s_time + 4.0, raw_end))

        if (e_time - s_time) < 3.0:
            e_time = min(total_duration, s_time + 4.0)

        return round(s_time, 2), round(min(total_duration, e_time), 2)

    def snap_cuts_sequence(
        self,
        raw_cuts: List[Dict[str, Any]],
        transcription: FullTranscription,
        total_duration: float,
    ) -> List[ClipCut]:
        """Snaps each cut in a sequence without ever performing blind mathematical truncation."""
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

        # If too short, cleanly expand the last cut to the next sentence boundary
        if total_dur < 40.0:
            needed = 42.0 - total_dur
            last_cut = snapped_list[-1]
            target_end = min(total_duration, last_cut.end_time + needed)
            cands = [w for w in all_words if w.end >= target_end and w.end <= min(total_duration, target_end + 12.0)]
            if cands:
                best = max(cands, key=lambda w: (25.0 if any(w.word.strip().endswith(p) for p in [".", "!", "?"]) else 0.0) - abs(w.end - target_end))
                last_cut.end_time = best.end
            total_dur = sum(c.end_time - c.start_time for c in snapped_list)

        # If too long (> 58.5s), walk backward to an earlier sentence/clause ending instead of slicing blindly
        if total_dur > 58.5:
            last_cut = snapped_list[-1]
            max_allowed_last_end = last_cut.start_time + max(4.0, (last_cut.end_time - last_cut.start_time) - (total_dur - 58.0))
            earlier_words = [
                w for w in all_words
                if w.end <= max_allowed_last_end and w.end >= (last_cut.start_time + 4.0)
            ]
            if earlier_words:
                best_earlier = max(
                    earlier_words,
                    key=lambda w: (30.0 if any(w.word.strip().endswith(p) for p in [".", "!", "?"]) else 0.0) + w.end,
                )
                last_cut.end_time = best_earlier.end

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
        Refines raw LLM timestamps by intelligently snapping to exact sentence & word boundaries:
        1. Selects a natural, strong sentence opening (skips filler words and mid-sentence dangling conjunctions).
        2. Detects full sentence completions (prioritizing punctuation '.', '!', '?' and natural speech pauses >= 0.4s).
        3. Never cuts someone off midway through a word, syllable, or dangling thought.
        4. Adds natural release decay padding (+0.15s to +0.18s) so trailing consonants and speech resonance are preserved.
        5. Enforces valid duration strictly within [30.0s, max_duration] without arbitrary mathematical slicing.
        """
        all_words: List[Any] = []
        for seg in transcription.segments:
            all_words.extend(seg.words)

        if not all_words:
            s = max(0.0, raw_start)
            e = min(total_duration, s + min(max_duration, max(30.0, raw_end - raw_start)))
            return round(s, 2), round(e, 2)

        filler_words = {"um", "uh", "uhm", "er", "ah", "like", "so", "actually", "basically"}
        dangling_words = {
            "and", "but", "or", "because", "so", "then", "that", "which",
            "with", "if", "when", "to", "of", "in", "for", "the", "a", "an",
            "my", "your", "his", "her", "their", "our", "as", "than", "though",
        }
        sentence_enders = {".", "!", "?"}
        clause_enders = {",", ";", ":", "-", "—"}

        # -------------------------------------------------------------
        # STEP 1: Smart Start Snapping (Find natural sentence or clause start)
        # -------------------------------------------------------------
        closest_idx = min(range(len(all_words)), key=lambda i: abs(all_words[i].start - raw_start))

        # Check backwards up to 4 words or 1.8s for a clean sentence onset preceding raw_start
        start_idx = closest_idx
        for i in range(closest_idx, max(-1, closest_idx - 5), -1):
            if i == 0:
                start_idx = 0
                break
            prev_w = all_words[i - 1]
            prev_text = prev_w.word.strip()
            if any(prev_text.endswith(p) for p in sentence_enders) or (all_words[i].start - prev_w.end) >= 0.4:
                if abs(all_words[i].start - raw_start) <= 2.0:
                    start_idx = i
                    break

        # Skip leading filler words if the next word follows promptly (< 1.2s)
        while start_idx < len(all_words) - 1:
            clean_tok = all_words[start_idx].word.strip().lower().rstrip(".,!?;:-")
            if clean_tok in filler_words and (all_words[start_idx + 1].start - all_words[start_idx].end) < 1.2:
                start_idx += 1
            else:
                break

        snapped_start = all_words[start_idx].start

        # -------------------------------------------------------------
        # STEP 2: Smart Sentence-Ending Snapping
        # -------------------------------------------------------------
        min_dur = 35.0 if max_duration > 60.0 else 30.0
        min_end_time = snapped_start + min_dur
        max_end_time = min(total_duration, snapped_start + max_duration)

        raw_dur = raw_end - raw_start if raw_end > raw_start else 48.0
        target_len = max(min_dur, min(max_duration - 1.0, raw_dur))
        target_end_time = min(max_end_time - 0.2, snapped_start + target_len)

        # Candidates strictly within [min_end_time, max_end_time]
        end_candidates = [
            (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
            if (w.end + 0.15) <= max_end_time and w.end >= min_end_time
        ]

        if not end_candidates:
            # Expand downward if audio or transcript is shorter
            end_candidates = [
                (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
                if (w.end + 0.15) <= max_end_time and (w.end - snapped_start) >= 15.0
            ]

        if not end_candidates:
            valid_words = [
                (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
                if w.end <= max_end_time
            ]
            if valid_words:
                best_idx, best_end_word = max(valid_words, key=lambda it: it[1].end)
            else:
                return round(snapped_start, 2), round(min(total_duration, snapped_start + min(max_duration, 45.0)), 2)
        else:
            def score_end_cand(item: Tuple[int, Any]) -> float:
                idx, w = item
                text = w.word.strip()
                clean_tok = text.lower().rstrip(".,!?;:-")
                dist = abs(w.end - target_end_time)
                score = -dist * 1.5

                # Top Priority: Sentence-ending punctuation (. ! ?)
                if any(text.endswith(p) for p in sentence_enders):
                    score += 55.0
                elif any(text.endswith(p) for p in clause_enders):
                    score += 15.0

                # High Priority: Speech pause (silence or breath) after this word
                if idx < len(all_words) - 1:
                    pause = all_words[idx + 1].start - w.end
                    if pause >= 0.5:
                        score += 35.0
                    elif pause >= 0.3:
                        score += 18.0
                else:
                    score += 40.0

                # Severe Penalty: Hanging / dangling words that leave sentence mid-air
                if clean_tok in dangling_words:
                    score -= 60.0

                # Duration bonus for Shorts sweet spot (40s to 56s)
                dur = w.end - snapped_start
                if max_duration <= 60.0 and 40.0 <= dur <= 56.0:
                    score += 10.0

                return score

            best_idx, best_end_word = max(end_candidates, key=score_end_cand)

        # -------------------------------------------------------------
        # STEP 3: Natural Vocal Release Decay Padding (+0.15s)
        # -------------------------------------------------------------
        # Preserve trailing consonants and speech resonance cleanly
        if best_idx < len(all_words) - 1:
            next_word_start = all_words[best_idx + 1].start
            max_padding = max(0.0, next_word_start - best_end_word.end - 0.03)
            padding = min(0.18, max_padding)
        else:
            padding = min(0.18, max(0.0, total_duration - best_end_word.end))

        snapped_end = best_end_word.end + padding

        # Absolute hard bounds
        if (snapped_end - snapped_start) > max_duration:
            snapped_end = snapped_start + max_duration
        if snapped_end > total_duration:
            snapped_end = total_duration

        return round(max(0.0, snapped_start), 2), round(snapped_end, 2)

