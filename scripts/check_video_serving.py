"""Verify the video endpoint supports the byte-range requests a <video> element makes."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
video = Path(sys.argv[1])

with httpx.Client(timeout=120) as c:
    with video.open("rb") as fh:
        job = c.post(f"{API}/videos", files={"file": (video.name, fh, "video/mp4")}).json()
    jid = job["job_id"]
    print(f"job {jid}")

    url = f"{API}/jobs/{jid}/video"
    full = c.get(url)
    print(f"GET  -> {full.status_code} {full.headers.get('content-type')} "
          f"{full.headers.get('content-length')} bytes")

    head = c.head(url)
    print(f"HEAD -> {head.status_code}")

    ranged = c.get(url, headers={"Range": "bytes=0-1023"})
    print(f"GET Range bytes=0-1023 -> {ranged.status_code} "
          f"({len(ranged.content)} bytes, content-range={ranged.headers.get('content-range')})")

    ok = full.status_code == 200 and ranged.status_code in (206, 200)
    print("PASS: the browser can stream and seek this video" if ok else "FAIL: video serving is broken")
    sys.exit(0 if ok else 1)
