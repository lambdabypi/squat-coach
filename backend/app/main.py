"""FastAPI application.

The browser talks to this service for everything: upload, status, report, overlay and the
original video. The Next.js frontend holds no secrets and runs no inference.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

# Load squat-coach/.env before anything reads the environment, so the key never has to be
# exported by hand or pasted into a shell. The file is gitignored.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from . import cpu
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

# Upper bound on how long one SSE connection may stay open. Keep it just under the platform's
# request timeout so the stream ends itself with a clear message rather than being cut off.
#
# Configurable because the right value is a property of the host, not of this code. The local
# build analyses the common sample in 88s on a 6-core i7; the same image on Cloud Run managed
# 0.41 frames per second against 4.1 locally and blew through a 290s deadline twice, once at
# 2 vCPU and once at 4. Raising vCPU made it slower, not faster, most likely thread contention
# in MediaPipe's pool on a shared allocation. Sizing this from local timings was the mistake.
STREAM_DEADLINE_SECONDS = float(env("STREAM_DEADLINE_SECONDS", "290") or 290)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

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
        # Exposed because a 10x slowdown between this image running locally and the same image
        # running on Cloud Run turned out to be worth diagnosing rather than guessing at.
        "cpu": cpu.describe(),
        "stream_deadline_s": STREAM_DEADLINE_SECONDS,
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


@app.post("/analyses")
async def create_client_analysis(
    payload: str = Form(...),
    frames: list[UploadFile] = File(default=[]),
) -> dict:
    """Assess from landmarks the browser already computed, plus a decimated set of frames.

    The tracking that dominates the runtime moves to the device that has fast hardware. What
    stays here is the measurement layer, unchanged, so the numbers remain comparable with the
    locally verified run.

    `payload` is JSON: video metadata plus one entry per frame of MediaPipe landmarks. `frames`
    are JPEGs named by frame index (`42.jpg`), uploaded only for the subset the barbell detector
    needs.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"payload is not valid JSON: {exc}")

    for key in ("video", "frames"):
        if key not in data:
            raise HTTPException(status_code=400, detail=f"payload is missing '{key}'")
    if not data["frames"]:
        raise HTTPException(status_code=400, detail="payload contains no landmark frames")

    decoded: dict[int, "np.ndarray"] = {}
    for upload in frames:
        stem = Path(upload.filename or "").stem
        if not stem.isdigit():
            continue
        raw = await upload.read()
        if not raw:
            continue
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            decoded[int(stem)] = img

    job = store.create(data["video"].get("filename", "client-upload"), Path("client"))
    store.submit_client(job, data, decoded, use_agent=bool(env("ANTHROPIC_API_KEY")))
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


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    """Server-sent events: job progress and landmark previews on one held-open connection.

    This exists for Cloud Run as much as for the browser. Under request-based billing CPU is
    allocated only while a request is being processed, and a detached background thread is not
    request processing, so the analysis would crawl between short polls. A streaming response is
    still an in-flight request, so the instance keeps its CPU for the whole analysis and is
    billed only for that time. Polling every 700ms would have given the worker roughly a 1%
    duty cycle.

    The polling endpoints are kept for the CLI and for clients that cannot hold a connection.
    """
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")

    async def stream():
        sent_preview = 0
        last_status: tuple | None = None
        # A bound, so a wedged job cannot hold an instance open indefinitely.
        deadline = asyncio.get_event_loop().time() + STREAM_DEADLINE_SECONDS

        while True:
            current = (job.status, job.stage, round(job.progress, 3))
            if current != last_status:
                yield _sse("status", job.public())
                last_status = current

            if len(job.preview) > sent_preview:
                batch = job.preview[sent_preview:]
                sent_preview = len(job.preview)
                yield _sse("preview", {"frames": batch, "total": sent_preview})

            if job.status in ("done", "failed"):
                yield _sse("end", {"status": job.status, "error": job.error})
                return

            if asyncio.get_event_loop().time() > deadline:
                yield _sse("end", {"status": "timeout",
                                   "error": (
                                       f"The analysis did not finish within "
                                       f"{STREAM_DEADLINE_SECONDS:.0f}s. The work may still be "
                                       f"running; raise STREAM_DEADLINE_SECONDS and the "
                                       f"platform request timeout if this host is slower than "
                                       f"the deadline assumes."
                                   )})
                return

            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Proxies that buffer would defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


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
    print(f"[cpu]   {cpu.configure()}")
    print(f"[cpu]   {cpu.describe()}")
    if not env("ANTHROPIC_API_KEY"):
        print("[agent] ANTHROPIC_API_KEY is not set - running with the deterministic rule "
              "engine only. Findings and measurements are unaffected; wording is plainer.")
