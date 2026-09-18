"""Measure where the 60 seconds actually goes, and what each speed-up would buy.

Published benchmarks are run on other people's hardware with other people's footage. This runs
the real options against the common sample on this machine, so the future-work numbers in
BUILD_NOTES are measured rather than cited.

    python scripts/bench_speed.py <video>
"""

from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "backend" / "models"
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.bar import BarDetector  # noqa: E402

VARIANTS = {
    "lite": "pose_landmarker_lite.task",
    "full": "pose_landmarker_full.task",
    "heavy": "pose_landmarker_heavy.task",
}
BASE_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_{v}/float16/1/pose_landmarker_{v}.task")


def ensure(variant: str) -> Path:
    path = MODELS / VARIANTS[variant]
    if not path.exists():
        url = BASE_URL.format(v=variant)
        print(f"  downloading {variant}...", flush=True)
        urllib.request.urlretrieve(url, path)
    return path


def frames(video: Path, scale: float = 1.0):
    cap = cv2.VideoCapture(str(video))
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if scale != 1.0:
            f = cv2.resize(f, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        yield f
    cap.release()


def run(video: Path, variant: str, scale: float, hough_every: int | None) -> dict:
    """One pass. hough_every=None disables bar detection; 1 is every frame."""
    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ensure(variant))),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
    )
    detector = BarDetector() if hough_every else None
    n = 0
    found = 0
    t0 = time.perf_counter()
    with PoseLandmarker.create_from_options(opts) as lm:
        for i, frame in enumerate(frames(video, scale)):
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = lm.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                int(round(i * 1000 / 30.0)),
            )
            lms = res.pose_landmarks[0] if res.pose_landmarks else None
            found += lms is not None
            if detector is not None and i % hough_every == 0:
                detector.feed(i, frame, lms)
            n += 1
    elapsed = time.perf_counter() - t0
    out = {
        "variant": variant, "scale": scale, "hough_every": hough_every,
        "frames": n, "seconds": round(elapsed, 1),
        "fps": round(n / elapsed, 1), "detected": found,
    }
    if detector is not None:
        bar = detector.finalise()
        out["bar_observed_pct"] = round(bar.observed_fraction * 100)
    return out


def main() -> int:
    video = Path(sys.argv[1])
    clip_s = 7.92

    configs = [
        ("shipped: heavy + Hough every frame", "heavy", 1.0, 1),
        ("heavy, no bar detection", "heavy", 1.0, None),
        ("heavy + Hough every 5th frame", "heavy", 1.0, 5),
        ("full + Hough every 5th frame", "full", 1.0, 5),
        ("lite + Hough every 5th frame", "lite", 1.0, 5),
        ("full + Hough every 5th, half resolution", "full", 0.5, 5),
        ("lite + Hough every 5th, half resolution", "lite", 0.5, 5),
    ]

    print(f"{video.name}, {clip_s}s clip\n")
    rows = []
    for label, variant, scale, every in configs:
        print(f"running: {label}", flush=True)
        r = run(video, variant, scale, every)
        r["label"] = label
        r["realtime_x"] = round(r["seconds"] / clip_s, 1)
        rows.append(r)

    print(f"\n{'configuration':44s} {'sec':>6s} {'fps':>6s} {'xRT':>6s} {'pose':>6s} {'bar%':>6s}")
    print("-" * 80)
    base = rows[0]["seconds"]
    for r in rows:
        bar = f"{r.get('bar_observed_pct', 0)}%" if r.get("hough_every") else "-"
        print(f"{r['label']:44s} {r['seconds']:6.1f} {r['fps']:6.1f} "
              f"{r['realtime_x']:6.1f} {r['detected']:6d} {bar:>6s}")
    print()
    for r in rows[1:]:
        print(f"  {r['label']:44s} {base / r['seconds']:4.1f}x faster than shipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
