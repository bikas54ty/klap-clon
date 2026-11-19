"""Real pipeline: download -> transcribe -> find moments -> score -> select.

1. yt-dlp downloads YouTube / Twitch / Kick (VOD or video URL).
2. FFmpeg extracts 16 kHz mono audio.
3. faster-whisper transcribes locally with word timestamps.
   If local Whisper fails and OPENAI_API_KEY is set, OpenAI Whisper API
   is used as a fallback.
4. An LLM (OpenAI or Gemini) ranks transcript windows and writes
   title / hook / caption / hashtags. Without an API key, an honest
   heuristic scorer runs instead and every clip is labelled mode="heuristic".
5. Non-overlapping 20-45s moments are selected (configurable).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .db import data_dir, update_clip, update_job
from .models import Clip, Job, detect_platform

# ---------------------------------------------------------------------------
# Scoring keywords (heuristic fallback)
# ---------------------------------------------------------------------------
VIRAL_WORDS = {
    "insane", "crazy", "unbelievable", "impossible", "secret", "never",
    "always", "first", "worst", "best", "huge", "massive", "shocking",
    "wild", "dead", "killed", "won", "lost", "banned", "exposed",
    "truth", "real", "actually", "literally", "bro", "wait", "look",
    "oh my god", "no way", "what the", "holy", "wow", "amazing",
    "funny", "laugh", "cry", "scared", "angry", "money", "million",
    "billion", "free", "hack", "trick", "mistake", "fail", "win",
}
LAUGH_WORDS = {"haha", "lol", "lmao", "hahaha", "funny", "laughing"}

ProgressFn = Callable[[str, int], None]


def _noop_progress(stage: str, pct: int) -> None:
    pass


# ---------------------------------------------------------------------------
# 1. Download
# ---------------------------------------------------------------------------
def download_video(url: str, job_id: int) -> tuple[Path, str, Optional[float]]:
    """Download with yt-dlp. Returns (video_path, title, duration_sec).

    Raises RuntimeError with a clear message for live streams that cannot
    be downloaded yet, and for platform blocks (suggesting cookies).
    """
    import yt_dlp

    platform = detect_platform(url)
    out_dir = data_dir() / "uploads"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"job{job_id}.%(ext)s")

    ydl_opts: dict = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    cookies = os.environ.get("YTDLP_COOKIES", "").strip()
    if cookies and Path(cookies).exists():
        ydl_opts["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp could not read this URL.")
        if info.get("is_live"):
            raise RuntimeError(
                "This stream is still LIVE. yt-dlp cannot clip a live stream "
                "while it is running — wait for the VOD to appear, then paste "
                "the VOD link. (A live recorder is not in v1.)"
            )
        title = info.get("title") or f"{platform} video"
        duration = info.get("duration")
        # yt-dlp already wrote the file; find it.
        for ext in ("mp4", "mkv", "webm", "mov"):
            p = out_dir / f"job{job_id}.{ext}"
            if p.exists():
                return p, title, float(duration) if duration else None
        # Fallback: newest file matching the job prefix.
        matches = sorted(out_dir.glob(f"job{job_id}.*"), key=lambda p: p.stat().st_mtime)
        if matches:
            return matches[-1], title, float(duration) if duration else None
        raise RuntimeError("Download finished but no video file was found.")


# ---------------------------------------------------------------------------
# 2. Audio extraction
# ---------------------------------------------------------------------------
def extract_audio(video_path: Path, job_id: int) -> Path:
    audio = data_dir() / "uploads" / f"job{job_id}.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not audio.exists():
        raise RuntimeError(f"FFmpeg audio extraction failed: {r.stderr[-500:]}")
    return audio


def probe_duration(video_path: Path) -> Optional[float]:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 3. Transcription
# ---------------------------------------------------------------------------
def transcribe(audio_path: Path) -> list[dict]:
    """Return segments: [{start, end, text, words: [{start, end, word}]}].

    Local faster-whisper first; OpenAI Whisper API as fallback.
    """
    model_name = os.environ.get("WHISPER_MODEL", "base")
    device = os.environ.get("WHISPER_DEVICE", "auto")
    if device == "auto":
        try:
            import torch  # type: ignore  # noqa: F401
            device = "cuda"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"

    last_err: Optional[Exception] = None
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device=device, compute_type=compute)
        segments, _info = model.transcribe(
            str(audio_path), beam_size=5, word_timestamps=True, vad_filter=True
        )
        out: list[dict] = []
        for seg in segments:
            words = [
                {"start": float(w.start), "end": float(w.end), "word": w.word}
                for w in (seg.words or [])
            ]
            out.append({
                "start": float(seg.start), "end": float(seg.end),
                "text": seg.text.strip(), "words": words,
            })
        if out:
            return out
        raise RuntimeError("Whisper returned no segments.")
    except Exception as e:  # noqa: BLE001 - fall through to API fallback
        last_err = e

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"Local Whisper failed ({last_err}) and no OPENAI_API_KEY is set for the Whisper API fallback.")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1", file=f, response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )
        out = []
        for seg in (resp.segments or []):
            words = [
                {"start": float(w["start"]), "end": float(w["end"]), "word": w["word"]}
                for w in (getattr(resp, "words", None) or [])
                if seg["start"] <= w["start"] <= seg["end"]
            ]
            out.append({
                "start": float(seg["start"]), "end": float(seg["end"]),
                "text": seg["text"].strip(), "words": words,
            })
        if not out:
            raise RuntimeError("Whisper API returned no segments.")
        return out
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Transcription failed. Local Whisper: {last_err}. Whisper API: {e}")


# ---------------------------------------------------------------------------
# 4a. Chunking the transcript into scoreable windows
# ---------------------------------------------------------------------------
def chunk_transcript(segments: list[dict], target_seconds: float = 35.0) -> list[dict]:
    """Group word/segment stream into ~target_seconds windows on sentence ends."""
    chunks: list[dict] = []
    cur_text: list[str] = []
    cur_words: list[dict] = []
    start: Optional[float] = None
    end: float = 0.0
    for seg in segments:
        for w in seg.get("words") or [{"start": seg["start"], "end": seg["end"], "word": seg["text"]}]:
            if start is None:
                start = float(w["start"])
            cur_words.append(w)
            cur_text.append(w["word"])
            end = float(w["end"])
            text = " ".join(cur_text)
            # Close a chunk at a sentence end once it is long enough.
            if end - (start or 0) >= target_seconds and re.search(r"[.!?]\s*$", text.strip()):
                chunks.append({"start": start, "end": end, "text": text.strip(), "words": list(cur_words)})
                cur_text, cur_words, start = [], [], None
    if cur_text and start is not None:
        chunks.append({"start": start, "end": end, "text": " ".join(cur_text).strip(), "words": list(cur_words)})
    return chunks


# ---------------------------------------------------------------------------
# 4b. Heuristic scoring (no LLM key) — honest fallback, labelled as such
# ---------------------------------------------------------------------------
def heuristic_score(chunk: dict) -> int:
    text = chunk["text"].lower()
    words = text.split()
    if not words:
        return 10
    score = 35.0  # base: every spoken moment is at least watchable
    viral_hits = sum(1 for w in VIRAL_WORDS if w in text)
    score += min(25, viral_hits * 5)
    score += min(10, text.count("?") * 3)          # questions hook viewers
    score += min(8, text.count("!") * 2)           # excitement
    score += min(7, sum(1 for w in LAUGH_WORDS if w in text) * 3)
    score += min(5, len(re.findall(r"\b\d+\b", text)))  # numbers / stakes
    # Energy proxy: fast speech in the window.
    dur = max(1.0, chunk["end"] - chunk["start"])
    wpm = len(words) / dur * 60
    if 130 <= wpm <= 200:
        score += 5
    # Very short / very long windows are less clip-like.
    if dur < 15:
        score -= 10
    return int(max(5, min(98, round(score))))


def heuristic_copy(chunk: dict) -> dict:
    text = chunk["text"].strip()
    first = re.sub(r"[^A-Za-z0-9 ,.!?']", "", text)
    title = (first[:60].strip() or "Must-watch moment").rstrip(".!?")
    title = title[:1].upper() + title[1:] if title else "Must-watch moment"
    hook = first[:110].strip()
    hashtags = "#shorts #viral #clips"
    return {
        "title": title, "hook": hook,
        "caption": f"{hook} 🔥 #shorts #viral",
        "hashtags": hashtags,
    }


# ---------------------------------------------------------------------------
# 4c. LLM scoring
# ---------------------------------------------------------------------------
LLM_PROMPT = """You are a viral short-form video editor (Opus Clip / Klap style).
Below are transcript windows from a long video. Each has an id, start/end
seconds, and text. Score each window for VIRAL short-form potential
(0-100) as a 20-45 second vertical clip: hook in first 3 seconds,
emotion, surprise, story payoff, quotable lines, humour, drama.

Return ONLY valid JSON, a list of objects:
[{"id": 0, "score": 82, "title": "Short punchy title", "hook": "One-line hook",
  "caption": "Ready-to-post caption, 1-2 sentences",
  "hashtags": "#shorts #viral #gaming"}]

Score honestly. Most windows should be 40-75. Only truly great moments 85+.
Do not invent events not in the transcript.
"""

def score_with_llm(chunks: list[dict]) -> Optional[list[dict]]:
    """Return per-chunk LLM results, or None if no LLM is configured/available."""
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    payload = [
        {"id": i, "start": round(c["start"], 1), "end": round(c["end"], 1), "text": c["text"][:1200]}
        for i, c in enumerate(chunks)
    ]
    # Keep prompts bounded for very long videos: score in batches of 40.
    results: list[dict] = []
    for b in range(0, len(payload), 40):
        batch = payload[b:b + 40]
        raw: Optional[str] = None
        try:
            if provider == "gemini":
                import google.generativeai as genai

                genai.configure(api_key=os.environ["GEMINI_API_KEY"])
                model = os.environ.get("LLM_MODEL") or "gemini-2.0-flash"
                resp = genai.GenerativeModel(model).generate_content(
                    LLM_PROMPT + "\n" + json.dumps(batch)
                )
                raw = resp.text
            else:
                from openai import OpenAI

                client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
                model = os.environ.get("LLM_MODEL") or "gpt-4o-mini"
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": LLM_PROMPT + "\n" + json.dumps(batch)}],
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content
        except Exception:
            return None  # caller falls back to heuristic
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else parsed.get("clips") or parsed.get("results") or []
            results.extend(items if isinstance(items, list) else [])
        except (json.JSONDecodeError, AttributeError):
            # Try to salvage a JSON array from the text.
            m = re.search(r"\[.*\]", raw, re.S)
            if not m:
                return None
            try:
                results.extend(json.loads(m.group(0)))
            except json.JSONDecodeError:
                return None
    return results or None


# ---------------------------------------------------------------------------
# 5. Moment selection
# ---------------------------------------------------------------------------
def select_moments(chunks: list[dict], job: Job) -> list[Clip]:
    """Score chunks (LLM if possible, else heuristic) and pick
    non-overlapping moments clamped to [min_seconds, max_seconds]."""
    llm = score_with_llm(chunks) if (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    ) else None
    by_id = {}
    if llm:
        for item in llm:
            try:
                by_id[int(item["id"])] = item
            except (KeyError, TypeError, ValueError):
                continue

    scored: list[tuple[int, dict, dict]] = []
    for i, chunk in enumerate(chunks):
        item = by_id.get(i)
        if item and isinstance(item.get("score"), (int, float)):
            score = int(max(5, min(100, item["score"])))
            copy = {
                "title": str(item.get("title") or "")[:90] or heuristic_copy(chunk)["title"],
                "hook": str(item.get("hook") or "")[:160],
                "caption": str(item.get("caption") or "")[:280],
                "hashtags": str(item.get("hashtags") or "#shorts #viral"),
            }
            mode = "llm"
        else:
            score = heuristic_score(chunk)
            copy = heuristic_copy(chunk)
            mode = "heuristic"
        scored.append((score, chunk, {**copy, "mode": mode}))

    scored.sort(key=lambda t: t[0], reverse=True)

    picked: list[Clip] = []
    used: list[tuple[float, float]] = []
    for rank, (score, chunk, copy) in enumerate(scored):
        if len(picked) >= job.clip_count:
            break
        start, end = float(chunk["start"]), float(chunk["end"])
        # Clamp to requested length: prefer the start, trim the tail.
        if end - start > job.max_seconds:
            end = start + job.max_seconds
        if end - start < job.min_seconds:
            # Extend forward if possible, else accept the short moment.
            end = start + min(job.min_seconds, end - start + 5)
        if end - start < 10:
            continue
        if any(not (end <= u0 or start >= u1) for u0, u1 in used):
            continue
        used.append((start, end))
        picked.append(Clip(
            job_id=job.id, rank=len(picked), start=start, end=end,
            score=score, mode=copy["mode"], title=copy["title"],
            hook=copy["hook"], caption=copy["caption"], hashtags=copy["hashtags"],
        ))
    picked.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(picked):
        c.rank = i
    return picked


def format_timestamp(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def words_to_srt(words: list[dict]) -> str:
    """Group words into ~2s caption lines and render SRT."""
    lines: list[str] = []
    buf: list[dict] = []
    idx = 1

    def flush() -> None:
        nonlocal idx
        if not buf:
            return
        text = " ".join(w["word"] for w in buf).strip()
        lines.append(
            f"{idx}\n{_srt_timestamp(buf[0]['start'])}"
            f" --> {_srt_timestamp(buf[-1]['end'])}\n{text}\n"
        )
        idx += 1
        buf.clear()

    for w in words:
        if buf and w["start"] - buf[0]["start"] > 2.0:
            flush()
        buf.append(w)
    flush()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full job orchestration
# ---------------------------------------------------------------------------
def run_pipeline(job: Job, progress: ProgressFn = _noop_progress) -> list[Clip]:
    """Run download -> transcribe -> score -> render for one job.
    Updates the job row at every stage. Returns the finished clips."""
    from .render import render_clip  # late import: avoids a cycle at import time

    try:
        progress("downloading", 5)
        update_job(job.id, status="downloading", stage="downloading", progress=5)
        video_path, title, duration = download_video(job.url, job.id)
        if duration is None:
            duration = probe_duration(video_path)
        update_job(job.id, title=title, duration_sec=duration, source_path=str(video_path))

        progress("transcribing", 25)
        update_job(job.id, status="transcribing", stage="transcribing", progress=25)
        audio_path = extract_audio(video_path, job.id)
        segments = transcribe(audio_path)
        if not segments:
            raise RuntimeError("Transcription produced no text — is the audio muted?")

        progress("scoring", 55)
        update_job(job.id, status="scoring", stage="finding moments", progress=55)
        chunks = chunk_transcript(segments, target_seconds=float(job.max_seconds))
        if not chunks:
            raise RuntimeError("No scoreable moments found in the transcript.")
        moments = select_moments(chunks, job)
        if not moments:
            raise RuntimeError("No non-overlapping moments could be selected.")

        # Persist clip rows before rendering so the UI shows them early.
        from .db import create_clip

        for moment in moments:
            moment.id = create_clip(moment)

        progress("rendering", 65)
        update_job(job.id, status="rendering", stage="rendering", progress=65)
        total = len(moments)
        for i, moment in enumerate(moments):
            try:
                update_clip(moment.id, status="rendering")
                # Words inside this moment, for captions + SRT.
                words = []
                for seg in segments:
                    for w in seg.get("words") or []:
                        if moment.start <= w["start"] < moment.end:
                            words.append({**w, "start": w["start"] - moment.start,
                                          "end": w["end"] - moment.start})
                if not words:
                    words = [{"start": 0.0, "end": moment.end - moment.start,
                              "word": moment.title}]
                out_path, srt_path, thumb_path = render_clip(
                    video_path, moment, words, job.layout, job.caption_style, job.id
                )
                update_clip(
                    moment.id, status="done", file_path=str(out_path),
                    srt_path=str(srt_path), thumbnail_path=str(thumb_path),
                )
                moment.file_path, moment.srt_path = str(out_path), str(srt_path)
                moment.status = "done"
            except Exception as e:  # noqa: BLE001 - one bad clip must not kill the job
                update_clip(moment.id, status="failed", error=str(e)[:500])
                moment.status, moment.error = "failed", str(e)[:500]
            progress("rendering", 65 + int(30 * (i + 1) / max(1, total)))
            update_job(job.id, progress=65 + int(30 * (i + 1) / max(1, total)))

        done = sum(1 for m in moments if m.status == "done")
        if done == 0:
            raise RuntimeError("All clips failed to render. Check FFmpeg is installed.")
        progress("done", 100)
        update_job(job.id, status="done", stage="done", progress=100)
        return moments
    except Exception as e:  # noqa: BLE001
        update_job(job.id, status="failed", stage="failed", error=str(e)[:1000])
        raise
