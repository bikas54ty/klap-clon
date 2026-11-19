"""FastAPI app: job submission, job status, clip downloads.

Run:
    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000   # repo root
    uvicorn app.main:app --host 0.0.0.0 --port 8000           # backend/
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()  # also pick up a .env next to the working directory

from .db import create_job, data_dir, get_clip, get_job, init_db, list_jobs  # noqa: E402
from .models import Job, JobRequest, detect_platform  # noqa: E402

app = FastAPI(title="Klap Clone — AI Video Clipper", version="1.0.0")

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateJobBody(BaseModel):
    url: str
    clip_count: int = Field(default=10, ge=1, le=100)
    min_seconds: int = Field(default=20, ge=10, le=120)
    max_seconds: int = Field(default=45, ge=10, le=120)
    layout: str = "smart"
    caption_style: str = "bold"


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id, "url": job.url, "platform": job.platform,
        "title": job.title, "duration_sec": job.duration_sec,
        "status": job.status, "stage": job.stage, "progress": job.progress,
        "clip_count": job.clip_count, "min_seconds": job.min_seconds,
        "max_seconds": job.max_seconds, "layout": job.layout,
        "caption_style": job.caption_style, "error": job.error,
        "created_at": job.created_at,
        "clips": [
            {
                "id": c.id, "rank": c.rank, "start": c.start, "end": c.end,
                "duration": round(c.end - c.start, 1), "score": c.score,
                "mode": c.mode, "title": c.title, "hook": c.hook,
                "caption": c.caption, "hashtags": c.hashtags,
                "status": c.status, "error": c.error,
                "download_url": f"/api/clips/{c.id}/download" if c.status == "done" else None,
                "srt_url": f"/api/clips/{c.id}/srt" if c.status == "done" else None,
            }
            for c in job.clips
        ],
    }


@app.on_event("startup")
def _startup() -> None:
    init_db()


# Serve finished clips (thumbnails / direct file links) at /clips/...
_clips_dir = data_dir() / "clips"
_clips_dir.mkdir(parents=True, exist_ok=True)
app.mount("/clips", StaticFiles(directory=str(_clips_dir)), name="clips")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/jobs", status_code=201)
def create_job_endpoint(body: CreateJobBody, background: BackgroundTasks) -> dict:
    try:
        req = JobRequest(
            url=body.url, clip_count=body.clip_count,
            min_seconds=body.min_seconds, max_seconds=body.max_seconds,
            layout=body.layout, caption_style=body.caption_style,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    job = Job(
        url=req.url, platform=detect_platform(req.url), clip_count=req.clip_count,
        min_seconds=req.min_seconds, max_seconds=req.max_seconds,
        layout=req.layout, caption_style=req.caption_style,
    )
    job_id = create_job(job)
    if os.environ.get("RUN_WORKER_IN_API", "false").lower() == "true":
        # Dev only: run the pipeline in a background task of this process.
        from .pipeline import run_pipeline

        def _run(jid: int) -> None:
            j = get_job(jid)
            if j:
                try:
                    run_pipeline(j)
                except Exception:
                    pass  # error is already persisted on the job row

        background.add_task(_run, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job_endpoint(job_id: int) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@app.get("/api/jobs")
def list_jobs_endpoint(limit: int = 20) -> list[dict]:
    jobs = list_jobs(limit=limit)
    out = []
    for job in jobs:
        full = get_job(job.id) if job.id else None
        out.append(_job_to_dict(full) if full else _job_to_dict(job))
    return out


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: int):
    clip = get_clip(clip_id)
    if clip is None or not clip.file_path or not Path(clip.file_path).exists():
        raise HTTPException(status_code=404, detail="Clip file not ready yet")
    return FileResponse(clip.file_path, media_type="video/mp4",
                        filename=Path(clip.file_path).name)


@app.get("/api/clips/{clip_id}/srt")
def download_srt(clip_id: int):
    clip = get_clip(clip_id)
    if clip is None or not clip.srt_path or not Path(clip.srt_path).exists():
        raise HTTPException(status_code=404, detail="SRT not ready yet")
    return FileResponse(clip.srt_path, media_type="text/plain",
                        filename=Path(clip.srt_path).name)


# Backwards-compatible alias used by older clients.
@app.get("/api/clips/{clip_id}")
def get_clip_endpoint(clip_id: int) -> dict:
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {
        "id": clip.id, "job_id": clip.job_id, "rank": clip.rank,
        "start": clip.start, "end": clip.end, "score": clip.score,
        "mode": clip.mode, "title": clip.title, "hook": clip.hook,
        "caption": clip.caption, "hashtags": clip.hashtags,
        "status": clip.status, "error": clip.error,
    }
