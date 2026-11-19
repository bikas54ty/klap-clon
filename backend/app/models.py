"""Data models: validation + plain dataclasses for jobs and clips."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)")
TWITCH_RE = re.compile(r"twitch\.tv")
KICK_RE = re.compile(r"kick\.com")


def detect_platform(url: str) -> str:
    """Return 'youtube' | 'twitch' | 'kick' | 'unknown'."""
    u = url.lower()
    if YOUTUBE_RE.search(u):
        return "youtube"
    if TWITCH_RE.search(u):
        return "twitch"
    if KICK_RE.search(u):
        return "kick"
    return "unknown"


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    if detect_platform(url) == "unknown":
        raise ValueError(
            "Unsupported URL. Paste a YouTube, Twitch, or Kick link "
            "(video, VOD, channel, or live URL)."
        )
    return url


@dataclass
class JobRequest:
    url: str
    clip_count: int = 10
    min_seconds: int = 20
    max_seconds: int = 45
    layout: str = "smart"          # "smart" | "webcam-top"
    caption_style: str = "bold"    # "bold" | "karaoke" | "minimal" | "neon"

    def __post_init__(self) -> None:
        self.url = validate_url(self.url)
        if not 1 <= self.clip_count <= 100:
            raise ValueError("clip_count must be 1..100")
        if not 10 <= self.min_seconds <= 120:
            raise ValueError("min_seconds must be 10..120")
        if not self.min_seconds <= self.max_seconds <= 120:
            raise ValueError("max_seconds must be >= min_seconds and <= 120")
        if self.layout not in ("smart", "webcam-top"):
            raise ValueError("layout must be 'smart' or 'webcam-top'")
        if self.caption_style not in ("bold", "karaoke", "minimal", "neon"):
            raise ValueError("caption_style must be bold/karaoke/minimal/neon")


@dataclass
class Clip:
    id: Optional[int] = None
    job_id: Optional[int] = None
    rank: int = 0
    start: float = 0.0
    end: float = 0.0
    score: int = 0
    mode: str = "heuristic"        # "llm" | "heuristic"
    title: str = ""
    hook: str = ""
    caption: str = ""
    hashtags: str = ""
    file_path: str = ""
    srt_path: str = ""
    thumbnail_path: str = ""
    status: str = "pending"        # pending | rendering | done | failed
    error: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Job:
    id: Optional[int] = None
    url: str = ""
    platform: str = "unknown"
    title: str = ""
    duration_sec: Optional[float] = None
    status: str = "queued"         # queued | downloading | transcribing | scoring | rendering | done | failed
    stage: str = "queued"
    progress: int = 0
    clip_count: int = 10
    min_seconds: int = 20
    max_seconds: int = 45
    layout: str = "smart"
    caption_style: str = "bold"
    error: str = ""
    source_path: str = ""
    created_at: str = ""
    clips: list = field(default_factory=list)
