"""What actually happens when the uploaded video is not a side view?

The reference document defines its depth standard on the profile view (ref p.2, Fig 2-1, "Three
views of the squat. Profile view, Depth landmarks for the full squat."), and the assignment asks
for a side-view clip. So the interesting question is not whether a front view is supported, it is
whether the system *notices* and refuses, or quietly measures the wrong thing.

Front and oblique views are the dangerous case rather than the obvious one. Pose detection gets
BETTER as the athlete turns toward the camera, so every signal that normally indicates a bad
upload - low detection, missing landmarks - looks healthy. What breaks is the geometry: depth, back
angle and bar path are all defined in the sagittal plane, and a rotated camera measures a
projection of them while reporting the same numbers with the same units.

Rather than assert the gate works, this drives it. A true side view collapses the left and right
landmarks onto each other, so camera yaw is simulated by separating them, holding everything else
fixed. That is exactly the quantity `_view_ratio` measures, so this tests the gate and the refusal
path below it, not the pose model.

    python scripts/check_view_gate.py <side_view_video>
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker, PoseLandmarkerOptions, RunningMode,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import analyse_client_landmarks  # noqa: E402
from app.vision.pose import CLIENT_LANDMARK_INDICES, MODEL_PATH  # noqa: E402
from app.vision.probe import probe  # noqa: E402
from app.vision.quality import SAGITTAL_RATIO_MARGINAL, SAGITTAL_RATIO_OK  # noqa: E402

L_SH, R_SH, L_HIP, R_HIP = 11, 12, 23, 24

# Left/right separation as a fraction of torso length. The first is roughly what a real side view
# produces; the rest step through oblique toward square-on. A front view separates the shoulders by
# shoulder width, which is a substantial fraction of torso length, so it lands well above 0.40.
TARGET_RATIOS = [0.13, 0.30, 0.45, 0.80]


def collect(video: Path, fps: float, stride: int = 5):
    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO, num_poses=1,
    )
    frames_payload: list[dict] = []
    images: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(video))
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
                    entry["lm"][str(idx)] = [round(p.x, 6), round(p.y, 6), round(p.visibility, 3)]
            frames_payload.append(entry)
            if i % stride == 0:
                images[i] = frame
            i += 1
    cap.release()
    return frames_payload, images


def yaw(frames: list[dict], ratio: float, w: int, h: int) -> list[dict]:
    """Separate the left/right shoulders and hips to simulate turning toward the camera."""
    out = []
    for f in frames:
        lm = {k: list(v) for k, v in f["lm"].items()}
        keys = (str(L_SH), str(R_SH), str(L_HIP), str(R_HIP))
        if all(k in lm for k in keys):
            sx = (lm[str(L_SH)][0] + lm[str(R_SH)][0]) / 2
            sy = (lm[str(L_SH)][1] + lm[str(R_SH)][1]) / 2
            hx = (lm[str(L_HIP)][0] + lm[str(R_HIP)][0]) / 2
            hy = (lm[str(L_HIP)][1] + lm[str(R_HIP)][1]) / 2
            torso_px = float(np.hypot((sx - hx) * w, (sy - hy) * h))
            half = (ratio * torso_px / w) / 2.0     # back to normalised x
            lm[str(L_SH)][0], lm[str(R_SH)][0] = sx - half, sx + half
            lm[str(L_HIP)][0], lm[str(R_HIP)][0] = hx - half, hx + half
        out.append({"i": f["i"], "lm": lm})
    return out


def main() -> int:
    video = Path(sys.argv[1])
    info = probe(video)
    print(f"simulating camera yaw on {video.name}")
    print(f"gate bands: ok <= {SAGITTAL_RATIO_OK}, degraded <= {SAGITTAL_RATIO_MARGINAL}, "
          f"blocking above\n")
    frames, images = collect(video, info.fps)

    problems = 0
    for ratio in TARGET_RATIOS:
        payload = {
            "video": {
                "filename": video.name, "width": info.width, "height": info.height,
                "fps": info.fps, "duration_s": info.duration_s,
                "frame_count": info.frame_count, "codec": "client",
            },
            "frames": yaw(frames, ratio, info.width, info.height),
        }
        out = analyse_client_landmarks(payload, images, use_agent=False)
        rep = out["report"]
        q = rep["quality"]
        gate = next(g for g in q["gates"] if g["id"] == "sagittal_view")
        counts: dict[str, int] = {}
        for f in rep["findings"]:
            counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

        expect_block = ratio > SAGITTAL_RATIO_MARGINAL
        print(f"=== requested L/R separation {ratio:.2f} of torso ===")
        print(f"  measured view_ratio : {q['view_ratio']}")
        print(f"  gate                : {gate['severity']}  passed={gate['passed']}")
        print(f"  assessable          : {q['is_assessable']}")
        print(f"  blocked             : {bool(rep.get('blocked'))}")
        print(f"  verdicts            : {counts or 'none produced'}")

        if expect_block:
            # The only acceptable behaviour is a refusal. A pass here would mean the system
            # reporting sagittal-plane measurements from a camera that cannot see that plane.
            if q["is_assessable"] or not rep.get("blocked"):
                print("  PROBLEM: a non-sagittal view was assessed instead of refused")
                problems += 1
            elif counts.get("meets_standard") or counts.get("does_not_meet_standard"):
                print("  PROBLEM: refused overall yet still published pass/fail verdicts")
                problems += 1
            else:
                print("  -> refused, no pass/fail verdicts published")
            for r in q.get("blocking_reasons", []):
                print(f"     reason: {r}")
        else:
            if not q["is_assessable"]:
                print("  PROBLEM: a usable side view was refused")
                problems += 1
            else:
                print("  -> assessed, with the caveat the gate attaches at this angle")
        print()

    print("=" * 74)
    if problems:
        print(f"{problems} problem(s): the view gate does not behave as the skill declares.")
        return 1
    print("The gate refuses every view past the marginal band and assesses the ones inside it.")
    print("Note what this does NOT establish: the threshold itself is an engineering_tolerance,")
    print("picked without labelled footage at known camera angles, so where exactly the boundary")
    print("should sit between 0.25 and 0.40 is not calibrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
