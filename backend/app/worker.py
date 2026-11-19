"""Background worker: polls the SQLite queue and runs the pipeline.

Run it as a separate process (Docker `worker` service, or locally):

    python -m backend.app.worker        # from the repo root
    python -m app.worker                # from backend/

One job at a time, in FIFO order. Progress is written to the jobs table
so the API/UI can poll it. Set POLL_SECONDS to change the poll interval.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

# Allow running from repo root (`backend.app.worker`) or backend/ (`app.worker`).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from backend.app.db import claim_next_job, init_db  # noqa: E402
from backend.app.pipeline import run_pipeline  # noqa: E402


def main() -> None:
    init_db()
    poll = float(os.environ.get("POLL_SECONDS", "2"))
    print("[worker] started, polling SQLite queue", flush=True)
    while True:
        job = claim_next_job()
        if job is None:
            time.sleep(poll)
            continue
        print(f"[worker] job {job.id} {job.url}", flush=True)
        try:
            run_pipeline(job)
            print(f"[worker] job {job.id} done", flush=True)
        except Exception:
            traceback.print_exc()
            print(f"[worker] job {job.id} failed", flush=True)


if __name__ == "__main__":
    main()
