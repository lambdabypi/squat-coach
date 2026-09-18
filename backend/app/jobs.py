"""In-memory job store.

Deliberately simple: a dict and a thread pool. A queue, a database and a worker fleet are not
what this exercise is testing, and the limitation is stated in BUILD_NOTES - a restart loses
jobs, and the store does not survive more than one process.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Status = Literal["queued", "processing", "done", "failed"]

MAX_PREVIEW_FRAMES = 1200   # ~80s of clip at every 2nd frame; a bound, not an expectation


@dataclass
class Job:
    id: str
    filename: str
    path: Path
    status: Status = "queued"
    stage: str = "Queued"
    progress: float = 0.0
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    # Landmark snapshots emitted while tracking runs, so the user watches the analysis happen
    # instead of a progress bar. Bounded: a long clip must not grow this without limit.
    preview: list[dict] = field(default_factory=list)
    video_w: int = 0
    video_h: int = 0

    def public(self) -> dict:
        return {
            "job_id": self.id,
            "filename": self.filename,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobStore:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def create(self, filename: str, path: Path) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], filename=filename, path=path)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, job: Job, use_agent: bool = True) -> None:
        self._pool.submit(self._run, job, use_agent)

    def _run(self, job: Job, use_agent: bool) -> None:
        from .pipeline import analyse
        from .vision.probe import ProbeError

        def progress(stage: str, pct: float) -> None:
            job.stage = stage
            job.progress = pct

        def preview(payload: dict) -> None:
            if len(job.preview) < MAX_PREVIEW_FRAMES:
                job.preview.append(payload)

        job.status = "processing"
        job.stage = "Checking the video"
        try:
            job.result = analyse(
                job.path, use_agent=use_agent, progress=progress, preview=preview,
            )
            job.status = "done"
            job.stage = "Complete"
            job.progress = 1.0
        except ProbeError as exc:
            # A user-facing rejection: the message explains what to do about it.
            job.status = "failed"
            job.stage = "Rejected"
            job.error = str(exc)
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.stage = "Failed"
            job.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()


store = JobStore()
