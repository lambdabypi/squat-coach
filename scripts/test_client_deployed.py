"""Exercise the deployed client-landmark path exactly as the browser does.

Local runs of the client path look correct, yet the deployed report showed a "Target pose"
toggle with no panel behind it. The difference between the two is what the browser sends:
downscaled frames, downscaled dimensions in the payload, and JPEG rather than raw pixels. This
reproduces that, hits the real endpoint, and prints what the UI would receive.

    python scripts/test_client_deployed.py <video> <api_base>
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import cv2
import httpx
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker, PoseLandmarkerOptions, RunningMode,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.pose import CLIENT_LANDMARK_INDICES, MODEL_PATH  # noqa: E402

UPLOAD_MAX_WIDTH = 720      # matches frontend/lib/clientPose.ts
STRIDE = 5
JPEG_QUALITY = 72


def main() -> int:
    video = Path(sys.argv[1])
    api = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000").rstrip("/")

    cap = cv2.VideoCapture(str(video))
    w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = min(1.0, UPLOAD_MAX_WIDTH / w0)
    w, h = int(round(w0 * scale)), int(round(h0 * scale))
    fps = 30.0
    print(f"{video.name}: {w0}x{h0} -> browser sends {w}x{h}")

    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO, num_poses=1,
    )
    frames: list[dict] = []
    files: list[tuple[str, tuple[str, bytes, str]]] = []

    with PoseLandmarker.create_from_options(opts) as lm:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = lm.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                int(round(i * 1000 / fps)),
            )
            entry: dict = {"i": i, "lm": {}}
            if res.pose_landmarks:
                pts = res.pose_landmarks[0]
                for idx in CLIENT_LANDMARK_INDICES:
                    p = pts[idx]
                    entry["lm"][str(idx)] = [
                        round(p.x, 5), round(p.y, 5), round(p.visibility, 3)
                    ]
            frames.append(entry)
            if i % STRIDE == 0:
                small = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                ok2, buf = cv2.imencode(".jpg", small,
                                        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok2:
                    files.append(("frames", (f"{i}.jpg", buf.tobytes(), "image/jpeg")))
            i += 1
    cap.release()

    payload = {
        "video": {
            "filename": video.name, "width": w, "height": h, "fps": fps,
            "duration_s": len(frames) / fps, "frame_count": len(frames),
        },
        "frames": frames,
    }
    size = len(json.dumps(payload)) + sum(len(f[1][1]) for f in files)
    print(f"uploading {len(frames)} landmark frames + {len(files)} JPEGs "
          f"({size / 1e6:.1f} MB total)")

    with httpx.Client(timeout=600) as c:
        t0 = time.perf_counter()
        r = c.post(f"{api}/analyses", data={"payload": json.dumps(payload)}, files=files)
        if r.status_code >= 400:
            print(f"POST /analyses -> {r.status_code}: {r.text[:300]}")
            return 1
        job = r.json()
        jid = job["job_id"]
        print(f"job {jid}")

        while True:
            s = c.get(f"{api}/jobs/{jid}").json()
            if s["status"] in ("done", "failed"):
                break
            time.sleep(1.0)
        print(f"{s['status']} in {time.perf_counter() - t0:.1f}s")
        if s["status"] == "failed":
            print(f"error: {s['error']}")
            return 1

        report = c.get(f"{api}/jobs/{jid}/report").json()
        overlay = c.get(f"{api}/jobs/{jid}/overlay").json()

        counts: dict[str, int] = {}
        for f in report["findings"]:
            counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
        print(f"\nverdicts: {counts}")
        print(f"reps: {[r['index'] for r in report['reps']]}")
        print(f"bar: detected {report['bar']['observed_fraction']:.0%}, "
              f"usable {report['bar'].get('usable_fraction', 0):.0%}")
        print(f"scale: {report.get('scale') is not None}")

        tp = overlay.get("target_poses")
        print(f"\ntarget_poses present: {tp is not None}")
        if tp:
            print(f"keys as served: {sorted(tp.keys())}")
            for k, v in sorted(tp.items()):
                print(f"  rep {k}: solved={v['solved']} corrections={len(v['corrections'])} "
                      f"frame={v['frame']} (overlay has {len(overlay['frames'])} frames)")
                if v["frame"] >= len(overlay["frames"]):
                    print("    FRAME INDEX OUT OF RANGE -> PoseCompare would crash")
        else:
            print("  the UI toggle would show nothing, because there is nothing to show")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
