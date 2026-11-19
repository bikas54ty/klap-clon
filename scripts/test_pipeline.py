"""Smoke test for the Klap Clone pipeline — no download, no API key needed.

Usage:
    python scripts/test_pipeline.py
    python scripts/test_pipeline.py --smoke-file /path/to/short.mp4

The default run import-checks every backend module and unit-tests the
pure functions (platform detection, chunking, heuristic scoring, moment
selection, SRT/ASS generation). --smoke-file runs the full local pipeline
(transcribe + render) on a local video file, which needs FFmpeg and
faster-whisper installed.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import os
os.environ.setdefault("DATA_DIR", str(Path(tempfile.gettempdir()) / "klap-clone-test"))

from backend.app import models  # noqa: E402  (needed by _db_roundtrip / _smoke)


def check(name, fn):
    try:
        fn()
        print(f"  PASS {name}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {name}: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-file", default=None, help="Local mp4 to run end-to-end")
    args = ap.parse_args()

    ok = True
    print("Import checks:")
    from backend.app import db, main, models, pipeline, render, worker  # noqa: F401
    print("  PASS imports: db, main, models, pipeline, render, worker")

    print("Unit checks:")
    ok &= check("detect_platform youtube", lambda: _assert(models.detect_platform("https://www.youtube.com/watch?v=x") == "youtube"))
    ok &= check("detect_platform twitch", lambda: _assert(models.detect_platform("https://www.twitch.tv/videos/2932652958") == "twitch"))
    ok &= check("detect_platform kick", lambda: _assert(models.detect_platform("https://kick.com/xqc") == "kick"))
    ok &= check("validate_url rejects bad", lambda: _expect_error(lambda: models.validate_url("not a url")))
    ok &= check("JobRequest rejects clip_count=0", lambda: _expect_error(lambda: models.JobRequest(url="https://www.youtube.com/watch?v=x", clip_count=0)))
    ok &= check("JobRequest ok (100 clips)", lambda: _assert(models.JobRequest(url="https://www.twitch.tv/videos/2932652958", clip_count=100, layout="webcam-top").clip_count == 100))

    segs = [
        {"start": 0.0, "end": 5.0, "text": "Hello world.",
         "words": [{"start": 0.0, "end": 1.0, "word": "Hello"}, {"start": 1.0, "end": 2.0, "word": "world."}]},
        {"start": 5.0, "end": 40.0, "text": "This is insane! Did you see that? Wow, unbelievable, first time ever!",
         "words": [{"start": 5.0 + i, "end": 6.0 + i, "word": w} for i, w in enumerate("This is insane! Did you see that? Wow, unbelievable, first time ever!".split())]},
    ]
    chunks = pipeline.chunk_transcript(segs, target_seconds=10)
    ok &= check("chunk_transcript produces chunks", lambda: _assert(len(chunks) >= 1))
    ok &= check("heuristic_score viral > plain", lambda: _assert(
        pipeline.heuristic_score({"start": 5.0, "end": 40.0, "text": "This is insane! Did you see that? Wow, unbelievable!"})
        > pipeline.heuristic_score({"start": 0.0, "end": 5.0, "text": "Hello world, this is a normal sentence."})))
    job = models.Job(id=1, url="https://www.youtube.com/watch?v=x", clip_count=2, min_seconds=20, max_seconds=45)
    picked = pipeline.select_moments(chunks, job)
    ok &= check("select_moments returns clips", lambda: _assert(len(picked) >= 1 and picked[0].score > 0))
    ok &= check("words_to_srt", lambda: _assert("00:00:00,000" in pipeline.words_to_srt(segs[0]["words"])))
    tmp = Path(tempfile.gettempdir()) / "klap-test.ass"
    render.words_to_ass(segs[0]["words"], "bold", tmp)
    ok &= check("words_to_ass writes file", lambda: _assert(tmp.exists() and "[V4+ Styles]" in tmp.read_text()))
    ok &= check("db init + create/get job", lambda: _db_roundtrip())

    if args.smoke_file:
        print("End-to-end smoke test on:", args.smoke_file)
        ok &= check("smoke render", lambda: _smoke(args.smoke_file))

    print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


def _assert(cond):
    assert cond


def _expect_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def _db_roundtrip():
    from backend.app.db import create_job, get_job, init_db
    init_db()
    jid = create_job(models.Job(url="https://www.youtube.com/watch?v=x", platform="youtube"))
    assert get_job(jid) is not None


def _smoke(path: str):
    from backend.app.db import create_clip, create_job, init_db
    from backend.app.models import Clip, Job
    from backend.app.pipeline import extract_audio, transcribe
    from backend.app.render import render_clip

    init_db()
    video = Path(path)
    assert video.exists(), f"file not found: {path}"
    jid = create_job(Job(url="file://smoke", platform="youtube", clip_count=1))
    audio = extract_audio(video, jid)
    segments = transcribe(audio)
    assert segments, "no transcript"
    words = []
    for seg in segments:
        words.extend(seg.get("words") or [])
    clip = Clip(job_id=jid, rank=0, start=0.0, end=min(20.0, segments[-1]["end"]), score=80, mode="heuristic", title="Smoke test")
    out, srt, thumb = render_clip(video, clip, words, "smart", "bold", jid)
    assert out.exists() and srt.exists(), "render did not produce files"
    print(f"    rendered {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())
