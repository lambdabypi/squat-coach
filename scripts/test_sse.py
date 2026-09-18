"""Verify the SSE stream keeps a single request open for the whole analysis.

This is the property Cloud Run bills on: with request-based CPU allocation, the instance has CPU
while a request is in flight. A stream that stays open for the full analysis therefore gets
continuous CPU, where short polls would give the worker roughly a 1% duty cycle.

Asserts: one connection, status events throughout, preview events arriving during the run, and a
terminating end event.

    python scripts/test_sse.py <video> [api_base]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

video = Path(sys.argv[1])
API = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"


def main() -> int:
    with httpx.Client(timeout=400) as c:
        with video.open("rb") as fh:
            job = c.post(f"{API}/videos", files={"file": (video.name, fh, "video/mp4")}).json()
        jid = job["job_id"]
        print(f"job {jid}\n")

        t0 = time.perf_counter()
        statuses: list[str] = []
        preview_events = 0
        preview_frames = 0
        end: dict | None = None
        first_preview_at: float | None = None

        with c.stream("GET", f"{API}/jobs/{jid}/events") as r:
            print(f"stream opened: HTTP {r.status_code} {r.headers.get('content-type')}")
            event = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip())
                    el = time.perf_counter() - t0
                    if event == "status":
                        stage = data["stage"]
                        if not statuses or statuses[-1] != stage:
                            statuses.append(stage)
                            print(f"  {el:6.1f}s  status  {data['progress']:5.1%}  {stage}")
                    elif event == "preview":
                        preview_events += 1
                        preview_frames = data["total"]
                        if first_preview_at is None:
                            first_preview_at = el
                    elif event == "end":
                        end = data
                        print(f"  {el:6.1f}s  end     {data}")
                        break

        total = time.perf_counter() - t0
        print(f"\nstream held open for {total:.1f}s on ONE request")
        print(f"stages seen      : {len(statuses)}")
        print(f"preview events   : {preview_events} carrying {preview_frames} frames")
        if first_preview_at is not None:
            print(f"first preview at : {first_preview_at:.1f}s (during the run, not after)")

        ok = (
            end is not None
            and end.get("status") == "done"
            and preview_frames > 10
            and preview_events > 5
            and len(statuses) >= 3
        )
        if ok:
            rep = c.get(f"{API}/jobs/{jid}/report").json()
            counts: dict[str, int] = {}
            for f in rep["findings"]:
                counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
            print(f"report verdicts  : {counts}")
            print("\nPASS: one streaming request covered the entire analysis")
            return 0

        print("\nFAIL: the stream did not cover the analysis as expected")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
