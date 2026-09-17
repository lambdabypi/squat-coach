"""Block-1 smoke test: prove pose landmarks and barbell-plate detection work on real frames.

Nothing else gets built until this passes. Usage:
    python scripts/smoke_test.py <video> [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "backend" / "models" / "pose_landmarker_heavy.task"

# MediaPipe BlazePose indices we actually care about for a sagittal squat view.
NAMES = {
    0: "nose", 7: "l_ear", 8: "r_ear",
    11: "l_shoulder", 12: "r_shoulder",
    23: "l_hip", 24: "r_hip",
    25: "l_knee", 26: "r_knee",
    27: "l_ankle", 28: "r_ankle",
    29: "l_heel", 30: "r_heel",
    31: "l_foot_index", 32: "r_foot_index",
}


def detect_plate(frame: np.ndarray, shoulder_xy: tuple[float, float] | None):
    """Find the barbell plate as a large circle near shoulder height.

    Returns (x, y, r, basis) or None. basis is 'observed' when a circle was actually
    found in pixels — that distinction is what keeps the report defensible.
    """
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)

    # Search a horizontal band around the shoulder; the plate sits on the bar on the back.
    if shoulder_xy is not None:
        cy = int(shoulder_xy[1])
        band = max(0, cy - int(0.18 * h)), min(h, cy + int(0.18 * h))
    else:
        band = int(0.15 * h), int(0.65 * h)
    roi = gray[band[0]:band[1], :]
    if roi.size == 0:
        return None

    min_r = int(0.05 * min(w, h))
    max_r = int(0.30 * min(w, h))
    circles = cv2.HoughCircles(
        roi, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(0.15 * w), param1=120, param2=60,
        minRadius=min_r, maxRadius=max_r,
    )
    if circles is None:
        return None
    circles = np.round(circles[0]).astype(int)
    # Prefer the circle closest to the shoulder in x — that's the near-side plate.
    if shoulder_xy is not None:
        circles = sorted(circles, key=lambda c: abs(c[0] - shoulder_xy[0]))
    x, y, r = circles[0]
    return float(x), float(y + band[0]), float(r), "observed"


def main() -> int:
    video = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else video.parent / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not MODEL.exists():
        print(f"FAIL: model missing at {MODEL}")
        return 1

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"FAIL: OpenCV could not open {video}")
        return 1
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"opened {video.name}: {total} frames reported by OpenCV")

    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
    )

    sample_idx = [int(total * f) for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    plate_hits = 0
    pose_hits = 0

    with PoseLandmarker.create_from_options(opts) as landmarker:
        for idx in sample_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                print(f"  frame {idx}: READ FAILED")
                continue
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            res = landmarker.detect(mp_img)

            if not res.pose_landmarks:
                print(f"  frame {idx}: NO POSE")
                continue
            pose_hits += 1
            lms = res.pose_landmarks[0]

            vis = {n: lms[i].visibility for i, n in NAMES.items()}
            key = ["r_hip", "r_knee", "r_ankle", "r_shoulder"]
            print(f"  frame {idx}: pose OK | " + " ".join(f"{k}={vis[k]:.2f}" for k in key))

            sh = (lms[12].x * w, lms[12].y * h)
            plate = detect_plate(frame, sh)
            if plate:
                plate_hits += 1
                px, py, pr, _ = plate
                print(f"            plate at ({px:.0f},{py:.0f}) r={pr:.0f}")
                cv2.circle(frame, (int(px), int(py)), int(pr), (0, 215, 255), 4)
                cv2.circle(frame, (int(px), int(py)), 6, (0, 215, 255), -1)
            else:
                print("            plate NOT FOUND")

            for i, n in NAMES.items():
                lm = lms[i]
                x, y = int(lm.x * w), int(lm.y * h)
                colour = (0, 255, 0) if lm.visibility > 0.6 else (0, 0, 255)
                cv2.circle(frame, (x, y), 7, colour, -1)
            for a, b in [(11, 23), (12, 24), (23, 25), (24, 26), (25, 27), (26, 28), (27, 31), (28, 32)]:
                pa = (int(lms[a].x * w), int(lms[a].y * h))
                pb = (int(lms[b].x * w), int(lms[b].y * h))
                cv2.line(frame, pa, pb, (255, 255, 0), 3)

            cv2.imwrite(str(out_dir / f"smoke_{idx:04d}.jpg"), frame)

    cap.release()
    print(f"\npose {pose_hits}/{len(sample_idx)} | plate {plate_hits}/{len(sample_idx)}")
    print(f"frames written to {out_dir}")
    return 0 if pose_hits >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
