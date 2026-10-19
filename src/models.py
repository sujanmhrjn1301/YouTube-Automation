"""
Domain models and data contracts for YouTube Shorts automation pipeline.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    """Supported LLM providers for viral moment detection."""
    OPENAI = "openai"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"


class CropMode(str, Enum):
    """Reframing strategies for vertical 9:16 Shorts video."""
    FACE_TRACKING = "face_tracking"
    BLURRED_BACKGROUND = "blurred_background"
    CENTER_CROP = "center_crop"


class WhisperModelSize(str, Enum):
    """Faster-whisper model sizes."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large-v3"


class WordTimestamp(BaseModel):
    """Word-level alignment timestamp."""
    word: str
    start: float
    end: float
    probability: float = 1.0


class TranscriptionSegment(BaseModel):
    """Full sentence/phrase segment with nested word timestamps."""
    id: int
    start: float
    end: float
    text: str
    words: List[WordTimestamp] = Field(default_factory=list)


class FullTranscription(BaseModel):
    """Aggregated transcript with metadata."""
    language: str
    language_probability: float
    duration: float
    segments: List[TranscriptionSegment] = Field(default_factory=list)
    total_words: int = 0


class ViralClip(BaseModel):
    """Structured viral candidate output from LLM analysis."""
    start_time: float = Field(..., description="Start timestamp in seconds")
    end_time: float = Field(..., description="End timestamp in seconds")
    hook_title: str = Field(..., description="Punchy, attention-grabbing YouTube Shorts title")
    description: str = Field(..., description="Engaging description with relevant hashtags")
    tags: List[str] = Field(default_factory=list, description="SEO tags for viral reach")
    viral_reasoning: str = Field(..., description="Detailed explanation of why this moment hooks viewers")
    hook_score: int = Field(default=8, ge=1, le=10, description="Hook potential rating from 1 to 10")


class VideoMetadata(BaseModel):
    """Source video metadata from yt-dlp."""
    video_id: str
    title: str
    duration: float
    author: str
    resolution: str
    video_path: str
    audio_path: str
    filesize_mb: float


class FaceTrackingBox(BaseModel):
    """Bounding box coordinates for detected face."""
    x: int
    y: int
    w: int
    h: int
    center_x: int
    center_y: int
    confidence: float = 1.0


class PipelineRunResult(BaseModel):
    """Final output result summary of pipeline execution."""
    success: bool
    source_url: str
    video_metadata: Optional[VideoMetadata] = None
    selected_clip: Optional[ViralClip] = None
    cropped_video_path: Optional[str] = None
    subtitled_video_path: Optional[str] = None
    youtube_video_id: Optional[str] = None
    youtube_video_url: Optional[str] = None
    supabase_storage_url: Optional[str] = None
    supabase_record_id: Optional[str] = None
    error_message: Optional[str] = None
