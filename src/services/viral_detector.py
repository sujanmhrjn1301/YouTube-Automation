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
4. FULL NARRATIVE RESOLUTION & ZERO CLIFFHANGERS (CRITICAL):
   - NEVER end the clip on a build-up, anticipation clause, or cliffhanger (e.g. "look at what happens", "watch this", "wait for it", "he's about to...").
   - The clip MUST capture the COMPLETE resolution: the action outcome, the fail/win, the punchline, the reaction, the laughter, or the answer to the curiosity hook.
   - Always extend the end timestamp through the climax to capture 5 to 15 seconds of the immediate reaction/aftermath.
5. Target Length: 59.0 seconds is strictly the MINIMUM floor, NOT a ceiling or limit. Total runtime should be between 59.0 and 150.0 seconds. If a scene, story, or event needs 75s, 90s, 110s, or 130s to reach its full payoff and reaction, YOU MUST EXTEND IT. You have up to 150.0 seconds—use the necessary time to deliver a satisfying climax and payoff.
6. High Shareability: High emotional payoff, counter-intuitive insight, comedy, life hack, or controversial debate point.

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
                "Select a single continuous, uninterrupted viral moment from the broadcast strictly between 59.0 and 150.0 seconds. "
                "CRITICAL PAYOFF & RESOLUTION MANDATE: 59.0 seconds is strictly the MINIMUM floor, NOT a limit or ceiling. "
                "NEVER cut off right as something is about to happen! If tension or action is building up, you MUST extend the clip "
                "through the entire climax, outcome, and immediate reaction/laughter (allowing 70s, 90s, 120s, up to 150.0s). "
                "CRITICAL SPEECH INTEGRITY: The moment MUST start cleanly at the onset of a sentence and MUST end completely at a sentence finish (. ! ?). "
                "Never cut off someone speaking midway. Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            )
            duration_rule = "Total Duration MUST be between 59.0 and 150.0 seconds (minimum 59.0s floor; extend up to 150.0s to capture full climax and reaction)."
            max_clip_duration = 150.0
        elif allow_multi_cut:
            cut_instruction = (
                "Select the most viral sequence strictly between 59.0 and 150.0 seconds total runtime. "
                "CRITICAL PAYOFF MANDATE: 59.0 seconds is strictly the MINIMUM floor, NOT a ceiling. "
                "The final cut MUST include the complete resolution, punchline, and reaction. Never end on a cliffhanger or anticipation. "
                "Every cut MUST end cleanly on a completed clause or sentence. Never cut off someone mid-word."
            )
            duration_rule = "Total Duration MUST be between 59.0 and 150.0 seconds (minimum 59.0s floor; extend up to 150.0s for complete payoff)."
            max_clip_duration = 150.0
        else:
            cut_instruction = (
                "Select a single continuous, uninterrupted viral moment strictly between 59.0 and 150.0 seconds. "
                "CRITICAL PAYOFF & RESOLUTION MANDATE: 59.0 seconds is strictly the MINIMUM floor, NOT a limit or ceiling. "
                "NEVER end the clip right as something is about to happen! If an action, story, or joke is building up, you MUST extend the clip "
                "past the climax to include the outcome, scream, laugh, or reaction (e.g. 70s, 90s, 110s, up to 150.0s). "
                "CRITICAL SPEECH INTEGRITY: The moment MUST start cleanly at the beginning of a sentence and MUST end completely at a sentence finish (. ! ?). "
                "Under NO circumstances cut off someone who is speaking midway or leave a thought dangling. "
                "Do not split into multiple cuts; provide a single contiguous start_time and end_time."
            )
            duration_rule = "Total Duration MUST be between 59.0 and 150.0 seconds (minimum 59.0s floor; extend up to 150.0s to capture full climax and reaction)."
            max_clip_duration = 150.0

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
                snapped_start, snapped_end = self.snap_to_word_boundaries(raw_start, raw_end, transcription, max_limit, max_duration=max_clip_duration, min_duration=59.0)
                snapped_cuts = [ClipCut(start_time=snapped_start, end_time=snapped_end, role="clip")]
        else:
            snapped_start, snapped_end = self.snap_to_word_boundaries(raw_start, raw_end, transcription, max_limit, max_duration=max_clip_duration, min_duration=59.0)
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

        # Enforce minimum 59.0s: cleanly expand the last cut to the next sentence boundary, or first cut backwards
        min_target = min(59.0, total_duration)
        if total_dur < min_target:
            needed = min_target - total_dur
            last_cut = snapped_list[-1]
            target_end = min(total_duration, last_cut.end_time + needed)
            cands = [w for w in all_words if w.end >= target_end and w.end <= min(total_duration, target_end + 20.0)]
            if cands:
                best = max(cands, key=lambda w: (25.0 if any(w.word.strip().endswith(p) for p in [".", "!", "?"]) else 0.0) - abs(w.end - target_end))
                last_cut.end_time = best.end
            else:
                last_cut.end_time = target_end
            total_dur = sum(c.end_time - c.start_time for c in snapped_list)
            # If still under min_target, expand the first cut backwards to earlier sentence boundary
            if total_dur < min_target:
                deficit = min_target - total_dur
                earlier_start_cands = [
                    w for w in all_words
                    if w.start <= max(0.0, snapped_list[0].start_time - deficit)
                ]
                if earlier_start_cands:
                    best_start = min(earlier_start_cands, key=lambda w: abs(w.start - max(0.0, snapped_list[0].start_time - deficit)))
                    snapped_list[0].start_time = best_start.start
                else:
                    snapped_list[0].start_time = max(0.0, snapped_list[0].start_time - deficit)

        # Enforce maximum 150.0s: walk backward to an earlier sentence/clause ending instead of slicing blindly
        max_target = 150.0
        total_dur = sum(c.end_time - c.start_time for c in snapped_list)
        if total_dur > max_target:
            last_cut = snapped_list[-1]
            max_allowed_last_end = last_cut.start_time + max(4.0, (last_cut.end_time - last_cut.start_time) - (total_dur - max_target))
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
            else:
                last_cut.end_time = max_allowed_last_end

        return snapped_list

    def snap_to_word_boundaries(
        self,
        raw_start: float,
        raw_end: float,
        transcription: FullTranscription,
        total_duration: float,
        max_duration: float = 150.0,
        min_duration: float = 59.0,
    ) -> Tuple[float, float]:
        """
        Refines raw LLM timestamps by intelligently snapping to exact sentence & word boundaries:
        1. Selects a natural, strong sentence opening (skips filler words and mid-sentence dangling conjunctions).
        2. Detects full sentence completions (prioritizing punctuation '.', '!', '?' and natural speech pauses >= 0.4s).
        3. Never cuts someone off midway through a word, syllable, or dangling thought.
        4. Adds natural release decay padding (+0.15s to +0.18s) so trailing consonants and speech resonance are preserved.
        5. Enforces valid duration strictly within [59.0s, max_duration] (or total_duration if total_duration < 59.0s).
        """
        effective_min = min(min_duration, total_duration)
        effective_max = min(max_duration, total_duration)

        all_words: List[Any] = []
        for seg in transcription.segments:
            all_words.extend(seg.words)

        if not all_words:
            s = max(0.0, raw_start)
            if total_duration >= effective_min and (total_duration - s) < effective_min:
                s = max(0.0, total_duration - effective_min)
            raw_d = raw_end - raw_start if raw_end > raw_start else effective_min
            d = max(effective_min, min(effective_max, raw_d))
            e = min(total_duration, s + d)
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

        # Check backwards up to 5 words for a clean sentence onset preceding raw_start
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

        # Ensure snapped_start leaves at least effective_min seconds before total_duration
        if total_duration >= effective_min and (total_duration - snapped_start) < effective_min:
            target_start_limit = max(0.0, total_duration - effective_min)
            earlier_indices = [
                i for i in range(start_idx)
                if all_words[i].start <= target_start_limit
            ]
            if earlier_indices:
                best_start_idx = earlier_indices[-1]
                for i in reversed(earlier_indices):
                    if i == 0:
                        best_start_idx = 0
                        break
                    prev_w = all_words[i - 1]
                    if any(prev_w.word.strip().endswith(p) for p in sentence_enders) or (all_words[i].start - prev_w.end) >= 0.4:
                        best_start_idx = i
                        break
                start_idx = best_start_idx
                snapped_start = all_words[start_idx].start
            else:
                start_idx = 0
                snapped_start = all_words[0].start

        # -------------------------------------------------------------
        # STEP 2: Smart Sentence-Ending Snapping
        # -------------------------------------------------------------
        raw_dur = raw_end - raw_start if raw_end > raw_start else effective_min
        target_len = max(effective_min, min(effective_max - 1.0, raw_dur))
        min_end_time = snapped_start + effective_min
        max_end_time = min(total_duration, snapped_start + effective_max)
        target_end_time = min(max_end_time - 0.2, snapped_start + target_len)

        # Candidates strictly within [min_end_time, max_end_time]
        end_candidates = [
            (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
            if (w.end + 0.15) <= max_end_time and w.end >= min_end_time
        ]

        if not end_candidates:
            # If speech ends too early from current snapped_start, attempt moving start_idx earlier
            if start_idx > 0:
                for earlier_idx in reversed(range(start_idx)):
                    potential_start = all_words[earlier_idx].start
                    candidates_now = [
                        (idx, w) for idx, w in enumerate(all_words[earlier_idx:], start=earlier_idx)
                        if (w.end + 0.15) <= min(total_duration, potential_start + effective_max) and w.end >= (potential_start + effective_min)
                    ]
                    if candidates_now:
                        start_idx = earlier_idx
                        snapped_start = potential_start
                        min_end_time = snapped_start + effective_min
                        max_end_time = min(total_duration, snapped_start + effective_max)
                        target_end_time = min(max_end_time - 0.2, snapped_start + target_len)
                        end_candidates = candidates_now
                        break

        if not end_candidates:
            valid_words = [
                (idx, w) for idx, w in enumerate(all_words[start_idx:], start=start_idx)
                if w.end <= max_end_time
            ]
            if valid_words:
                best_idx, best_end_word = max(valid_words, key=lambda it: it[1].end)
            else:
                return round(snapped_start, 2), round(min(total_duration, snapped_start + effective_min), 2)
        else:
            def score_end_cand(item: Tuple[int, Any]) -> float:
                idx, w = item
                text = w.word.strip()
                clean_tok = text.lower().rstrip(".,!?;:-")
                
                # Asymmetric distance penalty: penalize ending too early much more than extending to capture the payoff
                if w.end < target_end_time:
                    dist_penalty = (target_end_time - w.end) * 1.8
                else:
                    dist_penalty = (w.end - target_end_time) * 0.4
                score = -dist_penalty

                # Top Priority: Sentence-ending punctuation (. ! ?)
                if any(text.endswith(p) for p in sentence_enders):
                    score += 55.0
                    # Major bonus for excitement, reaction, shock, laughter endings
                    if text.endswith("!"):
                        score += 25.0
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

                # Severe Penalty: Anticipation / cliffhanger phrases (clip ends right as something is about to happen)
                preceding_tokens = [
                    all_words[j].word.strip().lower().rstrip(".,!?;:-")
                    for j in range(max(start_idx, idx - 4), idx + 1)
                ]
                anticipation_stems = {
                    "watch", "look", "wait", "see", "about", "ready", "incoming", "next",
                    "gonna", "going", "happens", "happened", "check", "listen", "guess",
                    "suddenly", "starts", "trying"
                }
                if any(tok in anticipation_stems for tok in preceding_tokens):
                    score -= 75.0

                # Generous duration bonus across 59s to 120s range
                dur = w.end - snapped_start
                if 59.0 <= dur <= 110.0:
                    score += 20.0
                elif dur > 110.0:
                    score += 10.0

                return score

            best_idx, best_end_word = max(end_candidates, key=score_end_cand)

        # -------------------------------------------------------------
        # STEP 3: Natural Vocal Release Decay Padding (+0.18s to +0.30s)
        # -------------------------------------------------------------
        target_padding = 0.30 if any(best_end_word.word.strip().endswith(p) for p in ["!", "?"]) else 0.18
        if best_idx < len(all_words) - 1:
            next_word_start = all_words[best_idx + 1].start
            max_padding = max(0.0, next_word_start - best_end_word.end - 0.03)
            padding = min(target_padding, max_padding)
        else:
            padding = min(target_padding, max(0.0, total_duration - best_end_word.end))

        snapped_end = best_end_word.end + padding

        # Absolute hard bounds: max_duration
        if (snapped_end - snapped_start) > effective_max:
            snapped_end = snapped_start + effective_max
        if snapped_end > total_duration:
            snapped_end = total_duration

        # Absolute hard bounds: min_duration
        if (snapped_end - snapped_start) < effective_min and total_duration >= effective_min:
            if snapped_start + effective_min <= total_duration:
                snapped_end = snapped_start + effective_min
            else:
                snapped_end = total_duration
                snapped_start = max(0.0, snapped_end - effective_min)

        return round(max(0.0, snapped_start), 2), round(snapped_end, 2)

