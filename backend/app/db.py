"""SQLite storage for jobs and clips. No ORM — plain sqlite3, one file."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Clip, Job


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")).resolve()


def db_path() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "uploads").mkdir(parents=True, exist_ok=True)
    (d / "clips").mkdir(parents=True, exist_ok=True)
    return d / "jobs.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'unknown',
                title TEXT NOT NULL DEFAULT '',
                duration_sec REAL,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                clip_count INTEGER NOT NULL DEFAULT 10,
                min_seconds INTEGER NOT NULL DEFAULT 20,
                max_seconds INTEGER NOT NULL DEFAULT 45,
                layout TEXT NOT NULL DEFAULT 'smart',
                caption_style TEXT NOT NULL DEFAULT 'bold',
                error TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                rank INTEGER NOT NULL DEFAULT 0,
                start REAL NOT NULL DEFAULT 0,
                end REAL NOT NULL DEFAULT 0,
                score INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'heuristic',
                title TEXT NOT NULL DEFAULT '',
                hook TEXT NOT NULL DEFAULT '',
                caption TEXT NOT NULL DEFAULT '',
                hashtags TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL DEFAULT '',
                srt_path TEXT NOT NULL DEFAULT '',
                thumbnail_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job: Job) -> int:
    init_db()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO jobs (url, platform, title, duration_sec, status, stage,
                   progress, clip_count, min_seconds, max_seconds, layout,
                   caption_style, error, source_path, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job.url, job.platform, job.title, job.duration_sec, job.status,
             job.stage, job.progress, job.clip_count, job.min_seconds,
             job.max_seconds, job.layout, job.caption_style, job.error,
             job.source_path, _now()),
        )
        return int(cur.lastrowid)


def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))


def get_job(job_id: int) -> Optional[Job]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        clips = [
            _row_to_clip(r)
            for r in conn.execute(
                "SELECT * FROM clips WHERE job_id = ? ORDER BY rank", (job_id,)
            ).fetchall()
        ]
        return _row_to_job(row, clips)


def list_jobs(limit: int = 20) -> list[Job]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for row in rows:
            n = conn.execute(
                "SELECT COUNT(*) c FROM clips WHERE job_id = ? AND status = 'done'",
                (row["id"],),
            ).fetchone()["c"]
            job = _row_to_job(row, [])
            job.clips = []  # list view: no clip payload, count in progress field is job progress
            out.append(job)
        return out


def claim_next_job() -> Optional[Job]:
    """Atomically claim the oldest queued job for the worker. Returns None if none."""
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'downloading', stage = 'downloading', progress = 1 WHERE id = ?",
            (row["id"],),
        )
        return _row_to_job(row, [])


def create_clip(clip: Clip) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO clips (job_id, rank, start, end, score, mode, title, hook,
                   caption, hashtags, file_path, srt_path, thumbnail_path, status, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (clip.job_id, clip.rank, clip.start, clip.end, clip.score, clip.mode,
             clip.title, clip.hook, clip.caption, clip.hashtags, clip.file_path,
             clip.srt_path, clip.thumbnail_path, clip.status, clip.error),
        )
        return int(cur.lastrowid)


def update_clip(clip_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE clips SET {sets} WHERE id = ?", (*fields.values(), clip_id))


def get_clip(clip_id: int) -> Optional[Clip]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _row_to_clip(row) if row else None


def _row_to_job(row: sqlite3.Row, clips: list[Clip]) -> Job:
    return Job(
        id=row["id"], url=row["url"], platform=row["platform"], title=row["title"],
        duration_sec=row["duration_sec"], status=row["status"], stage=row["stage"],
        progress=row["progress"], clip_count=row["clip_count"],
        min_seconds=row["min_seconds"], max_seconds=row["max_seconds"],
        layout=row["layout"], caption_style=row["caption_style"],
        error=row["error"], source_path=row["source_path"],
        created_at=row["created_at"], clips=clips,
    )


def _row_to_clip(row: sqlite3.Row) -> Clip:
    return Clip(
        id=row["id"], job_id=row["job_id"], rank=row["rank"], start=row["start"],
        end=row["end"], score=row["score"], mode=row["mode"], title=row["title"],
        hook=row["hook"], caption=row["caption"], hashtags=row["hashtags"],
        file_path=row["file_path"], srt_path=row["srt_path"],
        thumbnail_path=row["thumbnail_path"], status=row["status"], error=row["error"],
    )
