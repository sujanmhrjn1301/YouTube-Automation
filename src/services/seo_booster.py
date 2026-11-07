"""
Stage 6+ SEO & Algorithm Optimization Booster for YouTube.
Generates high-ranking, high-CTR metadata (titles, descriptions, tags)
specifically optimized for YouTube Search and Suggested Videos rail.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


class YouTubeSEOBooster:
    """Automates YouTube algorithm optimization for Shorts, Longform, and Montages."""

    DEFAULT_CREATOR = "IShowSpeed"

    # High-ranking search keywords for Speed content
    DEFAULT_SPEED_TAGS = [
        "IShowSpeed",
        "Speed",
        "IShowSpeed clips",
        "IShowSpeed highlights",
        "IShowSpeed funny moments",
        "Speed stream highlights",
        "IShowSpeed live",
        "Speed scream",
        "Speed reactions",
        "Viral",
        "Trending",
        "LiveStream",
    ]

    @staticmethod
    def detect_creator(text: str) -> str:
        t = text.lower()
        if "speed" in t or "ishowspeed" in t:
            return "IShowSpeed"
        if "mrbeast" in t or "beast" in t:
            return "MrBeast"
        if "kai" in t or "cenat" in t:
            return "Kai Cenat"
        return "IShowSpeed"

    def optimize_title(self, raw_title: str, is_short: bool = True, source_title: str = "") -> str:
        """
        Produce a high-CTR, search-optimized title.
        Ensures:
          1. Creator name is present for search intent.
          2. Specific event keywords are clear.
          3. High emotional hook.
          4. Shorts keep #Shorts hashtag; Longform has curiosity parenthetical.
          5. Under 90 chars so it does not get truncated on mobile search results.
        """
        title = raw_title.strip()

        # Remove existing #shorts or generic prefixes
        title = re.sub(r"#shorts\b", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"^(short\s*#?\d+|viral\s*short\s*#?\d+)[:\s-]*", "", title, flags=re.IGNORECASE).strip()

        # Extract creator
        creator = self.detect_creator(title + " " + source_title)
        if creator.lower() not in title.lower():
            title = f"{creator} {title}".strip()

        # Clean multiple spaces and trailing punctuation
        title = re.sub(r"\s+", " ", title)
        title = title.rstrip(" -_:,")

        if is_short:
            # For Shorts: punchy, under 65 chars, with #Shorts
            hook_words = ["INSANE", "UNHINGED", "NO WAY", "BRO CRASHED OUT", "TERRIFYING"]
            # If title is very short, add energy
            if len(title) < 30 and not any(h in title.upper() for h in hook_words):
                title = f"{title}! 😱"
            
            # Keep under 65 chars so #Shorts fits without truncation
            if len(title) > 65:
                title = title[:62].rstrip() + "..."
            
            if not title.lower().endswith("#shorts"):
                title = f"{title} #Shorts"
            return title
        else:
            # For Longform/Montage: narrative curiosity hook
            if not any(h in title.upper() for h in ["GONE WRONG", "HORRIBLY", "MISTAKE", "UNHINGED", "SURVIVED", "CHAOS"]):
                if len(title) <= 55:
                    title = f"{title}... It Went HORRIBLY WRONG!"
            
            if "(FULL" not in title.upper() and "(BEST" not in title.upper() and len(title) <= 70:
                title = f"{title} (Full Highlights)"
            
            if len(title) > 90:
                title = title[:87].rstrip() + "..."
            return title

    def build_seo_description(
        self,
        title: str,
        is_short: bool = True,
        source_title: str = "",
        channel_name: str = "IShowSpeed",
        chapters_str: str = "",
    ) -> str:
        """
        Constructs an elite SEO description:
          - First 200 characters: High-intent keyword search snippet.
          - Context & attribution: Triggers YouTube Suggested / Up-Next algorithm.
          - Timestamps: Triggers Google/YouTube Key Moments rich snippets.
          - Search Queries: Natural search phrase coverage.
          - Hashtags: Trending algorithmic indexing.
        """
        creator = self.detect_creator(title + " " + source_title)
        clean_title = re.sub(r"#shorts\b", "", title, flags=re.IGNORECASE).strip()

        # 1. Primary 200-char Search Snippet (First 2 sentences indexed heavily by search crawlers)
        if is_short:
            search_hook = (
                f"Watch {creator}'s wildest and funniest reaction in this viral moment! "
                f"Check out what happens when {creator} completely loses it on stream."
            )
        else:
            search_hook = (
                f"{clean_title}.\n\n"
                f"The best unhinged and funniest moments from {creator}'s live stream, "
                f"edited into a high-retention cinematic narrative."
            )

        # 2. Suggested Video Association (Ties your video directly to the official stream in the sidebar)
        source_block = ""
        if source_title:
            source_block = (
                f"Original Stream: {source_title}\n"
                f"Creator: @{creator}\n"
            )
        else:
            source_block = f"Featuring: @{creator}\n"

        # 3. Chapters / Timestamps (Key Moments rich search results)
        chapters_block = ""
        if chapters_str and not is_short:
            chapters_block = f"\nTIMESTAMPS:\n{chapters_str.strip()}\n"

        # 4. Search Queries / Intent Cloud
        search_cloud = (
            f"Topics Covered:\n"
            f"- {creator} funniest stream moments\n"
            f"- {creator} live stream highlights\n"
            f"- {creator} best reactions and crash outs\n"
            f"- Trending gaming and stream clips\n"
        )

        # 5. Algorithmic Hashtags
        if is_short:
            hashtags = f"#{creator} #Shorts #YouTubeShorts #Trending #Viral #Highlights #Funny"
        else:
            hashtags = f"#{creator} #Highlights #LiveStream #BestMoments #Trending #Gaming"

        parts = [
            search_hook,
            source_block.strip(),
            chapters_block.strip() if chapters_block else None,
            search_cloud.strip(),
            hashtags.strip(),
        ]

        return "\n\n".join(p for p in parts if p)

    def build_seo_tags(
        self,
        title: str,
        source_title: str = "",
        existing_tags: Optional[List[str]] = None,
        is_short: bool = True,
    ) -> List[str]:
        """
        Combines broad authority creator tags, specific entity keywords,
        and high-volume format tags. Clamped to YouTube's 500-char API limit.
        """
        creator = self.detect_creator(title + " " + source_title)
        tags: List[str] = []

        # 1. Creator authority tags
        tags.extend([
            creator,
            f"{creator} clips",
            f"{creator} highlights",
            f"{creator} funny moments",
            f"{creator} stream",
            f"{creator} live",
            f"{creator} reaction",
        ])

        # 2. Specific topic keywords from title & source
        combined_text = f"{title} {source_title}".lower()
        topic_candidates = [
            "haunted house", "scary", "horror", "jumpscare", "speed scream",
            "gaming", "irl", "challenge", "barks", "speed bark", "funny moments",
            "streamer", "kai cenat", "mrbeast", "crash out", "best of"
        ]
        for topic in topic_candidates:
            if topic in combined_text:
                tags.append(topic.title())

        # 3. Format tags
        if is_short:
            tags.extend(["Shorts", "YouTube Shorts", "Short", "Viral Shorts", "Trending"])
        else:
            tags.extend(["Full Highlights", "Best Moments", "Longform", "Compilation", "Stream Highlights"])

        # 4. Include existing tags if any
        if existing_tags:
            for t in existing_tags:
                clean_t = t.strip()
                if clean_t and clean_t not in tags:
                    tags.append(clean_t)

        # Remove duplicates preserving order
        unique_tags = list(dict.fromkeys(tags))

        # Clamp total character length to 450 (YouTube limit is 500)
        final_tags = []
        total_len = 0
        for tag in unique_tags:
            if total_len + len(tag) + 1 > 450:
                break
            final_tags.append(tag)
            total_len += len(tag) + 1

        return final_tags

    def enhance_metadata(
        self,
        title: str,
        duration: float = 0.0,
        source_title: str = "",
        existing_description: str = "",
        existing_tags: Optional[List[str]] = None,
        chapters_str: str = "",
    ) -> Dict[str, Any]:
        """One-stop enhancement returning optimized title, description, and tags."""
        is_short = duration <= 180.0
        opt_title = self.optimize_title(title, is_short=is_short, source_title=source_title)

        # Preserve existing chapters if already generated in description
        if not chapters_str and "TIMESTAMPS:" in existing_description:
            try:
                chapters_str = existing_description.split("TIMESTAMPS:")[1].split("Creator:")[0].strip()
            except Exception:
                pass

        opt_description = self.build_seo_description(
            opt_title,
            is_short=is_short,
            source_title=source_title,
            chapters_str=chapters_str,
        )

        opt_tags = self.build_seo_tags(
            opt_title,
            source_title=source_title,
            existing_tags=existing_tags,
            is_short=is_short,
        )

        return {
            "title": opt_title,
            "description": opt_description,
            "tags": opt_tags,
            "is_short": is_short,
            "creator": self.detect_creator(opt_title + " " + source_title),
        }
