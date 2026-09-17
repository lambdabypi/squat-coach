"""End-to-end check against the running API: upload a real file, poll, fetch the report.

This exercises the path the brief requires to work on a newly uploaded video, rather than a
prepared result.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"
video = Path(sys.argv[1])


def main() -> int:
    with httpx.Client(timeout=120) as c:
        h = c.get(f"{API}/health").json()
        print(f"health: {h}")

        t0 = time.perf_counter()
        with video.open("rb") as fh:
            r = c.post(f"{API}/videos", files={"file": (video.name, fh, "video/mp4")})
        r.raise_for_status()
        job = r.json()
        print(f"uploaded -> job {job['job_id']} ({time.perf_counter() - t0:.1f}s)")

        last = None
        while True:
            s = c.get(f"{API}/jobs/{job['job_id']}").json()
            key = (s["stage"], round(s["progress"], 2))
            if key != last:
                print(f"  [{s['progress']:5.1%}] {s['stage']}")
                last = key
            if s["status"] in ("done", "failed"):
                break
            time.sleep(0.5)

        total = time.perf_counter() - t0
        if s["status"] == "failed":
            print(f"FAILED: {s['error']}")
            return 1

        rep = c.get(f"{API}/jobs/{job['job_id']}/report").json()
        ov = c.get(f"{API}/jobs/{job['job_id']}/overlay").json()
        vid = c.head(f"{API}/jobs/{job['job_id']}/video")

        print(f"\ndone in {total:.1f}s")
        print(f"report : {len(rep['findings'])} findings over {len(rep['reps'])} reps")
        print(f"overlay: {len(ov['frames'])} frames, {len(ov['bar_path'])} bar-path points")
        print(f"video  : HTTP {vid.status_code}, {vid.headers.get('content-length')} bytes")

        counts: dict[str, int] = {}
        for f in rep["findings"]:
            counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
        print(f"verdicts: {counts}")
        print(f"summary : {rep.get('summary') or '(no agent configured)'}")

        # The overlay must be JSON-clean: NaN would parse in Python but break the browser.
        import json
        raw = json.dumps(ov)
        assert "NaN" not in raw and "Infinity" not in raw, "overlay contains non-JSON floats"
        print("overlay JSON is browser-safe (no NaN/Infinity)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
