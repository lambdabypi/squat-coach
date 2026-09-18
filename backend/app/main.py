"""FastAPI application.

The browser talks to this service for everything: upload, status, report, overlay and the
original video. The Next.js frontend holds no secrets and runs no inference.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Load squat-coach/.env before anything reads the environment, so the key never has to be
# exported by hand or pasted into a shell. The file is gitignored.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .config import env, env_list
from .jobs import store
from .skill.loader import load_skill
from .vision.probe import (
    MAX_DURATION_S,
    MIN_FPS,
    MIN_SHORT_SIDE_PX,
    SUPPORTED_SUFFIXES,
)

STORAGE = Path(__file__).resolve().parents[1] / "storage" / "uploads"
STORAGE.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
ALLOWED_ORIGINS = env_list("ALLOWED_ORIGINS", DEFAULT_ORIGINS)

app = FastAPI(title="Squat Coach API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    skill = load_skill()
    return {
        "ok": True,
        "skill_version": skill.meta.skill_version,
        "criteria": len(skill.criteria),
        "agent_configured": bool(env("ANTHROPIC_API_KEY")),
    }


@app.get("/requirements")
def requirements() -> dict:
    """What the interface tells the user before they upload."""
    skill = load_skill()
    return {
        "formats": sorted(s.lstrip(".") for s in SUPPORTED_SUFFIXES),
        "max_duration_s": MAX_DURATION_S,
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "min_fps": MIN_FPS,
        "min_short_side_px": MIN_SHORT_SIDE_PX,
        "recording": [
            "Film from directly to one side, level with the lifter - this is a side-view analysis.",
            "Keep the whole body and the barbell in frame for the entire set, feet included.",
            "One set per clip. A few repetitions is plenty.",
            "Good, even light. A dark gym makes the barbell hard to track.",
        ],
        "coverage": skill.coverage_rows(),
    }


@app.get("/skill")
def get_skill() -> dict:
    """The skill, served so the UI can show exactly which rule produced a finding."""
    skill = load_skill()
    return {
        "meta": skill.meta.model_dump(mode="json"),
        "criteria": [c.model_dump(mode="json") for c in skill.criteria],
        "coverage": skill.coverage_rows(),
    }


@app.post("/videos")
async def upload_video(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"{suffix or 'That file type'} is not supported. "
                   f"Use one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
        )

    job_id_path = STORAGE / f"{os.urandom(6).hex()}{suffix}"
    size = 0
    with job_id_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                job_id_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
                           "Trim the clip to the working set and try again.",
                )
            out.write(chunk)

    if size == 0:
        job_id_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file was empty.")

    job = store.create(file.filename or job_id_path.name, job_id_path)
    store.submit(job, use_agent=bool(env("ANTHROPIC_API_KEY")))
    return job.public()


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job.public()


@app.get("/jobs/{job_id}/preview")
def job_preview(job_id: str, since: int = 0) -> dict:
    """Landmark snapshots produced so far, for the live view during tracking.

    Incremental: the client passes the count it already holds and gets only what is new, so
    polling stays cheap for the whole run rather than re-sending the clip every second.
    """
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    snapshot = job.preview[since:]
    return {
        "total": len(job.preview),
        "since": since,
        "frames": snapshot,
        "status": job.status,
        "stage": job.stage,
    }


@app.get("/jobs/{job_id}/report")
def job_report(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    if job.status == "failed":
        raise HTTPException(status_code=422, detail=job.error or "Analysis failed.")
    if job.status != "done" or job.result is None:
        raise HTTPException(status_code=409, detail="Analysis is still running.")
    return job.result["report"]


@app.get("/jobs/{job_id}/overlay")
def job_overlay(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Unknown job or analysis not finished.")
    return job.result["overlay"]


@app.api_route("/jobs/{job_id}/video", methods=["GET", "HEAD"])
def job_video(job_id: str):
    job = store.get(job_id)
    if job is None or not job.path.exists():
        raise HTTPException(status_code=404, detail="Unknown job.")
    return FileResponse(job.path, media_type="video/mp4", filename=job.filename)


@app.on_event("startup")
def _validate_skill_at_startup() -> None:
    """Fail loudly at boot if the skill is malformed, rather than mid-assessment."""
    skill = load_skill()
    print(f"[skill] v{skill.meta.skill_version}: {len(skill.criteria)} criteria "
          f"({len(skill.assessable)} assessable, {len(skill.unassessable)} not from a side view)")
    print(f"[cors]  allowed origins: {', '.join(ALLOWED_ORIGINS)}")
    if not env("ANTHROPIC_API_KEY"):
        print("[agent] ANTHROPIC_API_KEY is not set - running with the deterministic rule "
              "engine only. Findings and measurements are unaffected; wording is plainer.")
