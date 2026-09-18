"""Confirm the live preview actually streams landmarks while tracking runs.

A progress view that only populates after the job finishes would be theatre. This uploads a
clip and polls the incremental preview endpoint, asserting that frames arrive *during*
processing and that each poll returns only what is new.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
video = Path(sys.argv[1])


def main() -> int:
    with httpx.Client(timeout=120) as c:
        with video.open("rb") as fh:
            job = c.post(f"{API}/videos", files={"file": (video.name, fh, "video/mp4")}).json()
        jid = job["job_id"]
        print(f"job {jid}")

        since = 0
        samples: list[tuple[float, int, str]] = []
        t0 = time.perf_counter()
        arrived_during_processing = False

        while True:
            s = c.get(f"{API}/jobs/{jid}").json()
            p = c.get(f"{API}/jobs/{jid}/preview?since={since}").json()

            new = len(p["frames"])
            if new:
                assert p["frames"][0]["frame"] >= since * 2 - 2 or since == 0, "overlap in incremental fetch"
                since = p["total"]
                if s["status"] == "processing":
                    arrived_during_processing = True
            samples.append((time.perf_counter() - t0, p["total"], s["stage"]))

            if s["status"] in ("done", "failed"):
                break
            time.sleep(1.0)

        print(f"\n{'elapsed':>8s}  {'frames':>7s}  stage")
        for el, total, stage in samples:
            print(f"{el:7.1f}s  {total:7d}  {stage}")

        final = c.get(f"{API}/jobs/{jid}/preview?since=0").json()
        first = final["frames"][0] if final["frames"] else None
        print(f"\ntotal preview frames: {final['total']}")
        if first:
            print(f"sample joints: {list(first['joints'])}")
            print(f"sample values: {first['joints'].get('hip')}")

        ok = arrived_during_processing and final["total"] > 10
        print("\nPASS: landmarks streamed while tracking was still running"
              if ok else "\nFAIL: preview did not populate during processing")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
