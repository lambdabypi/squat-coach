"""Can this machine's GPU actually accelerate the pipeline?

Three separate questions, because the answer differs for each:
  1. Does MediaPipe expose a GPU delegate on this platform?
  2. Was OpenCV built with CUDA?
  3. Is there a CUDA-capable device at all?

Vendor claims about GPU support rarely mention the platform caveats, so this asks the installed
libraries directly.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "backend" / "models" / "pose_landmarker_heavy.task"


def line(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


def main() -> int:
    line("1. CUDA device")
    try:
        n = cv2.cuda.getCudaEnabledDeviceCount()
        print(f"   OpenCV reports {n} CUDA-enabled device(s)")
        if n == 0:
            print("   -> this OpenCV build has no CUDA support compiled in")
    except Exception as exc:
        print(f"   OpenCV has no cuda module at all: {type(exc).__name__}")
        print("   -> pip opencv-contrib-python is built WITHOUT CUDA; it is a CPU-only wheel")

    line("2. OpenCV build configuration")
    info = cv2.getBuildInformation()
    for key in ("CUDA", "cuDNN", "OpenCL"):
        rows = [l.strip() for l in info.splitlines() if l.strip().startswith(key)]
        print(f"   {key:8s} {rows[0] if rows else '(not mentioned)'}")

    line("3. MediaPipe GPU delegate")
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        PoseLandmarker, PoseLandmarkerOptions, RunningMode,
    )
    print(f"   platform: {sys.platform}")
    delegates = [d for d in dir(BaseOptions.Delegate) if not d.startswith("_")]
    print(f"   delegates exposed by the API: {delegates}")

    frame = np.zeros((480, 640, 3), np.uint8)
    import mediapipe as mp
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)

    for name in ("CPU", "GPU"):
        delegate = getattr(BaseOptions.Delegate, name, None)
        if delegate is None:
            print(f"   {name}: not exposed")
            continue
        try:
            opts = PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(MODEL), delegate=delegate),
                running_mode=RunningMode.IMAGE,
            )
            t0 = time.perf_counter()
            with PoseLandmarker.create_from_options(opts) as lm:
                for _ in range(5):
                    lm.detect(img)
            dt = (time.perf_counter() - t0) / 5
            print(f"   {name}: OK, {dt * 1000:.0f} ms per blank 640x480 frame")
        except Exception as exc:
            msg = str(exc).splitlines()[0][:160]
            print(f"   {name}: FAILED - {type(exc).__name__}: {msg}")

    line("Conclusion")
    print("   Read the three sections above together: a CUDA device is necessary but not")
    print("   sufficient. Both MediaPipe and OpenCV have to be built to use it on this platform.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
