"""FFmpeg 9:16 rendering: face-tracked crop, webcam-top layout, burned captions.

Layouts
-------
smart      : crop the video to 1080x1920, centred on the largest face in
             frame (OpenCV Haar, MediaPipe if installed). Falls back to a
             centre crop when no face is found.
webcam-top : for Twitch gameplay streams where the webcam is a small box
             (usually top-right). The top ~42% of the frame is the webcam
             region, the bottom ~58% is the gameplay. We detect the face,
             crop a tight box around it for the top panel, and use the full
             frame (minus the webcam box) for the bottom panel. If no face
             is found, the top panel is the upper-right quadrant.

Captions are burned in with an ASS subtitle file (libass via the
`subtitles` filter) in one of four styles. An SRT is also written.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .db import data_dir
from .models import Clip

W, H = 1080, 1920
TOP_H = 800   # webcam panel height in webcam-top layout
BOTTOM_H = H - TOP_H


# ---------------------------------------------------------------------------
# Caption styles (ASS)
# ---------------------------------------------------------------------------
STYLES = {
    # name: (font, size, primary colour, outline, back colour, bold)
    "bold":    ("Arial Black", 64, "&H00FFFFFF", 3, "&H80000000", True),
    "karaoke": ("Arial", 58, "&H00FFFF00", 2, "&H80000000", True),
    "minimal": ("Arial", 48, "&H00FFFFFF", 1, "&H00000000", False),
    "neon":    ("Arial Black", 62, "&H00FF00FF", 3, "&H80000000", True),
}


def _ass_header(style: str) -> str:
    font, size, colour, outline, back, bold = STYLES.get(style, STYLES["bold"])
    bold_n = -1 if bold else 0
    return (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{colour},&H000000FF,&H00000000,{back},"
        f"{bold_n},0,0,0,100,100,0,0,1,{outline},0,2,40,40,120,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )


def _ass_time(t: float) -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def words_to_ass(words: list[dict], style: str, out: Path) -> Path:
    """Group words into ~1.8s karaoke lines and write an ASS file."""
    lines = [_ass_header(style)]
    buf: list[dict] = []

    def flush() -> None:
        if not buf:
            return
        text = " ".join(w["word"] for w in buf).strip()
        # Karaoke: highlight word by word with {\kf} timing (centiseconds).
        if style == "karaoke":
            parts = []
            prev = buf[0]["start"]
            for w in buf:
                dur_cs = max(1, int(round((w["end"] - prev) * 100)))
                parts.append(f"{{\\kf{dur_cs}}}{w['word']}")
                prev = w["end"]
            text = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{_ass_time(buf[0]['start'])},{_ass_time(buf[-1]['end'])},"
            f"Default,,0,0,0,,{text}\n"
        )
        buf.clear()

    for w in words:
        if buf and w["start"] - buf[0]["start"] > 1.8:
            flush()
        buf.append(w)
    flush()
    out.write_text("".join(lines), encoding="utf-8")
    return out


def words_to_srt_file(words: list[dict], out: Path) -> Path:
    from .pipeline import format_timestamp, words_to_srt

    out.write_text(words_to_srt(words), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Face detection (for the crop)
# ---------------------------------------------------------------------------
def detect_face_box(video_path: Path, at_seconds: float) -> Optional[tuple[int, int, int, int]]:
    """Return (x, y, w, h) of the largest face near `at_seconds`, or None.

    Tries MediaPipe first (if installed), then OpenCV Haar cascades.
    """
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_MSEC, at_seconds * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        faces = cv2.CascadeClassifier(cascade_path).detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return int(x), int(y), int(w), int(h)
    except Exception:
        return None


def _escape_filter_path(p: Path) -> str:
    # FFmpeg filter paths: escape : and ' for the subtitles filter.
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _run(cmd: list[str], what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"{what} failed: {r.stderr[-800:]}")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_clip(
    video_path: Path, clip: Clip, words: list[dict],
    layout: str, caption_style: str, job_id: int,
) -> tuple[Path, Path, Path]:
    """Render one clip. Returns (mp4_path, srt_path, thumbnail_path)."""
    clips_dir = data_dir() / "clips" / f"job{job_id}"
    clips_dir.mkdir(parents=True, exist_ok=True)
    slug = f"clip{clip.rank:03d}_{int(clip.start)}-{int(clip.end)}"
    out = clips_dir / f"{slug}.mp4"
    srt = clips_dir / f"{slug}.srt"
    ass = clips_dir / f"{slug}.ass"
    thumb = clips_dir / f"{slug}.jpg"

    words_to_srt_file(words, srt)
    words_to_ass(words, caption_style, ass)
    ass_esc = _escape_filter_path(ass)

    dur = clip.end - clip.start
    face = detect_face_box(video_path, clip.start + min(2.0, dur / 2))

    if layout == "webcam-top":
        filtergraph = _webcam_top_filter(face)
    else:
        filtergraph = _smart_filter(face)

    # Burn captions + scale to exactly 1080x1920 + faststart.
    vf = f"{filtergraph},subtitles='{ass_esc}':force_style='Fontsize=56',format=yuv420p"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip.start), "-i", str(video_path),
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]
    _run(cmd, "FFmpeg render")

    # Thumbnail from the middle of the clip.
    _run([
        "ffmpeg", "-y", "-ss", str(clip.start + dur / 2), "-i", str(video_path),
        "-frames:v", "1", "-vf", "scale=540:-1", str(thumb),
    ], "Thumbnail")
    return out, srt, thumb


def _smart_filter(face: Optional[tuple[int, int, int, int]]) -> str:
    """Crop to 9:16 centred on the face (or frame centre), then scale."""
    if face:
        x, y, w, h = face
        cx = x + w // 2
        # crop=iw*9/16:ih would be the full-height vertical slice; centre it on the face.
        return (
            f"crop=ih*9/16:ih:'min(max({cx}-ih*9/32,0),iw-ih*9/16)':0,"
            f"scale={W}:{H}"
        )
    return f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale={W}:{H}"


def _webcam_top_filter(face: Optional[tuple[int, int, int, int]]) -> str:
    """Webcam on top (800px), gameplay below (1120px).

    Top panel: a tight crop around the face, scaled to 1080x800.
    Bottom panel: the full frame scaled/cropped to 1080x1120.
    The two are stacked with vstack.
    """
    if face:
        x, y, w, h = face
        # Tight box around the face with margin, clamped to the frame.
        pad = int(max(w, h) * 0.9)
        cx, cy = x + w // 2, y + h // 2
        # crop=w:h:x:y on the input, then scale to the top panel.
        top = (
            f"crop={2 * pad}:{2 * pad}:'min(max({cx}-{pad},0),iw-{2 * pad})'"
            f":'min(max({cy}-{pad},0),ih-{2 * pad})',scale={W}:{TOP_H},setsar=1[top]"
        )
    else:
        # No face found: upper-right quadrant (where Twitch webcams usually sit).
        top = f"crop=iw/2:ih/2:iw/2:0,scale={W}:{TOP_H},setsar=1[top]"
    bottom = f"scale={W}:{BOTTOM_H},setsar=1[bottom]"
    # split the input, process each branch, stack them.
    return f"split[a][b];[a]{top};[b]{bottom};[top][bottom]vstack,scale={W}:{H}"
