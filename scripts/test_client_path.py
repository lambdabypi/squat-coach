"""Do the client-landmark path and the server-decode path agree?

The whole justification for the hybrid is that only *where pose runs* changes, and the
measurement layer stays the single verified implementation. That is a claim, and this checks it:
run the video through the normal pipeline, then simulate a browser by replaying the same
landmarks plus a decimated set of frames through the client endpoint's code, and compare every
verdict and measurement.

Any divergence here means there are effectively two products, which is the failure the design
exists to avoid.

    python scripts/test_client_path.py <video> [frame_stride]
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

from app.pipeline import analyse, analyse_client_landmarks  # noqa: E402
from app.vision.pose import CLIENT_LANDMARK_INDICES, MODEL_PATH  # noqa: E402
from app.vision.probe import probe  # noqa: E402


def collect_like_a_browser(video: Path, fps: float, stride: int):
    """Produce exactly what the frontend will send: landmarks for every frame, images for some."""
    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
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
                    entry["lm"][str(idx)] = [
                        round(p.x, 5), round(p.y, 5), round(p.visibility, 3),
                    ]
            frames_payload.append(entry)
            if i % stride == 0:
                images[i] = frame
            i += 1
    cap.release()
    return frames_payload, images


def summarise(report: dict) -> tuple[dict, dict]:
    verdicts = {(f["rep_index"], f["criterion_id"]): f["verdict"] for f in report["findings"]}
    measures = {
        (f["rep_index"], f["criterion_id"]): f["measurement"]["value"]
        for f in report["findings"]
        if f.get("measurement") and f["measurement"].get("value") is not None
    }
    return verdicts, measures


def main() -> int:
    video = Path(sys.argv[1])
    stride = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    info = probe(video)

    print("=== server path (decodes the video, runs pose itself) ===")
    server = analyse(video, use_agent=False)["report"]
    sv, sm = summarise(server)
    print(f"  reps {len(server['reps'])}  findings {len(server['findings'])}  "
          f"bar observed {server['bar']['observed_fraction']:.0%}")

    print(f"\n=== simulating the browser: landmarks for all frames, images every {stride}th ===")
    payload_frames, images = collect_like_a_browser(video, info.fps, stride)
    print(f"  {len(payload_frames)} landmark frames, {len(images)} images "
          f"({len(images) / max(1, len(payload_frames)):.0%} of frames)")

    payload = {
        "video": {
            "filename": video.name, "width": info.width, "height": info.height,
            "fps": info.fps, "duration_s": info.duration_s,
            "frame_count": info.frame_count,
        },
        "frames": payload_frames,
    }

    print("\n=== client path (landmarks supplied, Hough on the uploaded frames only) ===")
    client = analyse_client_landmarks(payload, images, use_agent=False)["report"]
    cv_, cm = summarise(client)
    print(f"  reps {len(client['reps'])}  findings {len(client['findings'])}  "
          f"bar observed {client['bar']['observed_fraction']:.0%}")

    print("\n=== agreement ===")
    failures = 0

    print(f"  side:  server={server['pose']['side']}  client={client['pose']['side']}")
    if server["pose"]["side"] != client["pose"]["side"]:
        failures += 1
    print(f"  shin:  server={server['pose']['shin_length_px']}  "
          f"client={client['pose']['shin_length_px']}")

    flips = [(k, sv[k], cv_.get(k)) for k in sv if cv_.get(k) != sv[k]]
    if flips:
        print(f"\n  {len(flips)} VERDICT DIFFERENCE(S):")
        for (rep, cid), a, b in flips:
            print(f"    rep{rep} {cid:26s} {a} -> {b}")
        failures += len(flips)
    else:
        print(f"\n  all {len(sv)} verdicts identical")

    deltas = sorted(
        ((abs(cm[k] - v), k, v, cm[k]) for k, v in sm.items() if k in cm),
        reverse=True,
    )
    if deltas:
        print("\n  largest measurement differences:")
        for d, (rep, cid), a, b in deltas[:5]:
            print(f"    rep{rep} {cid:26s} {a:+8.3f} -> {b:+8.3f}  (delta {d:.4f})")

    print()
    if failures:
        print(f"{failures} difference(s): the two paths are NOT equivalent")
        return 1
    print("PASS: the client path reproduces the server path's verdicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
