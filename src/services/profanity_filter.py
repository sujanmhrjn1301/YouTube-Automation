"""
Profanity Filter & Audio Censor Bleep Service.
Detects English swear words / profanity from Whisper word timestamps
and generates exact bleep intervals for FFmpeg audio censorship.
"""

import re
from typing import Any, List, Set, Tuple

from src.console import log_info, log_warning


PROFANITY_WORDLIST: Set[str] = {
    # Core F-words
    "fuck", "fucking", "fucked", "fucker", "fuckers", "fucks", "fuckin", "fck", "fukin",
    "motherfucker", "motherfucking", "motherfuckers",
    # S-words
    "shit", "shitting", "shitted", "shits", "shitty", "bullshit", "horseshit",
    # P-words & gendered slurs
    "pussy", "pussies", "bitch", "bitches", "bitching", "bitchy", "cunt", "cunts",
    # Body parts & sexual terms used as profanity
    "dick", "dicks", "dickhead", "cock", "cocks", "cockhead", "asshole", "assholes",
    "dipshit", "dumbass", "jackass", "bastard", "bastards", "slut", "sluts", "whore", "whores",
    # Slurs
    "nigger", "niggers", "nigga", "niggas", "fag", "faggot", "faggots",
}

# Regex patterns to catch spaced, leetspeak, or trailing profanity variants
PROFANITY_PATTERNS = [
    re.compile(r"^f+u+c*k+(?:ing|ed|er|s)?$", re.IGNORECASE),
    re.compile(r"^sh+i+t+(?:ty|ting|s)?$", re.IGNORECASE),
    re.compile(r"^b+i+t+c+h+(?:es|ing)?$", re.IGNORECASE),
    re.compile(r"^p+u+s+s+y+$", re.IGNORECASE),
    re.compile(r"^c+u+n+t+s?$", re.IGNORECASE),
    re.compile(r"^d+i+c+k+(?:head|s)?$", re.IGNORECASE),
    re.compile(r"^a+s+s+h+o+l+e+s?$", re.IGNORECASE),
]


class ProfanityFilterService:
    """Detects profanity words and computes bleep intervals."""

    def __init__(self, custom_words: Set[str] = None) -> None:
        self.words = set(PROFANITY_WORDLIST)
        if custom_words:
            self.words.update(w.lower() for w in custom_words)

    def is_profane(self, word: str) -> bool:
        """Check if a single word is considered profane."""
        clean = re.sub(r"[^a-zA-Z]", "", word).lower()
        if not clean:
            return False
        if clean in self.words:
            return True
        for pat in PROFANITY_PATTERNS:
            if pat.match(clean):
                return True
        return False

    def find_profanity_intervals(
        self,
        transcription: Any,
        clip_start: float,
        clip_end: float,
    ) -> List[Tuple[float, float, str]]:
        """
        Find exact (relative_start, relative_end, word) time intervals for swear words
        spoken between clip_start and clip_end.
        Times are normalized relative to clip_start (0.0s = beginning of clip).
        """
        intervals: List[Tuple[float, float, str]] = []
        if not hasattr(transcription, "segments"):
            return []

        clip_dur = clip_end - clip_start

        for seg in transcription.segments:
            if not hasattr(seg, "words") or not seg.words:
                continue

            for w in seg.words:
                # Check if word falls within the clip window
                if w.end < (clip_start - 0.1) or w.start > (clip_end + 0.1):
                    continue

                raw_word = getattr(w, "word", "")
                if self.is_profane(raw_word):
                    # Compute timestamps relative to the rendered clip
                    rel_s = max(0.0, w.start - clip_start - 0.05)
                    rel_e = min(clip_dur, w.end - clip_start + 0.05)
                    if rel_e > rel_s:
                        intervals.append((round(rel_s, 2), round(rel_e, 2), raw_word.strip()))

        return intervals
