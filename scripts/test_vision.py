"""Headless check of the vision core: pose -> reps. Run before any UI exists."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from app.vision.bar import BarDetector  # noqa: E402
from app.vision.pose import extract_pose  # noqa: E402
from app.vision.probe import probe  # noqa: E402
from app.vision.reps import segment_reps  # noqa: E402


def main() -> int:
    video = Path(sys.argv[1])
    info = probe(video)
    print(f"{video.name}: {info.width}x{info.height} {info.fps:.1f}fps "
          f"{info.duration_s:.2f}s {info.frame_count} frames ({info.codec})")

    detector = BarDetector()
    t0 = time.perf_counter()
    track = extract_pose(video, info.fps, frame_sink=detector.feed)
    bar = detector.finalise()
    elapsed = time.perf_counter() - t0
    print(f"pose: {track.n} frames in {elapsed:.1f}s "
          f"({track.n / elapsed:.1f} fps, {elapsed / info.duration_s:.2f}x realtime)")
    print(f"detected in {int(track.detected.sum())}/{track.n} frames")
    print(f"camera-facing side: {track.side.upper()} (margin {track.side_confidence:.3f})")
    print(f"shin length: {track.shin_length_px():.1f} px")

    print("\nmean visibility by joint:")
    for j in sorted(track.vis):
        v = track.vis[j]
        print(f"  {j:9s} mean={v.mean():.2f}  >0.6 in {int((v > 0.6).sum()):3d}/{track.n} frames")

    obs = bar.basis_observed
    print(f"\nbar: observed in {int(obs.sum())}/{track.n} frames ({bar.observed_fraction:.0%}), "
          f"median radius {bar.median_radius:.1f}px")
    if bar.note:
        print(f"  note: {bar.note}")
    if obs.any():
        bx, by = bar.x[obs], bar.y[obs]
        shin = track.shin_length_px()
        print(f"  observed bar x: min={bx.min():.0f} max={bx.max():.0f} "
              f"std={bx.std():.1f}px = {bx.std() / shin:.3f} shin  <-- SMALL means a vertical path")
        print(f"  observed bar y: min={by.min():.0f} max={by.max():.0f} "
              f"range={by.max() - by.min():.0f}px  <-- LARGE means the squat was captured")

    seg = segment_reps(track)
    print(f"\nreps: {len(seg.reps)}")
    if seg.note:
        print(f"note: {seg.note}")
    for r in seg.reps:
        print(f"  rep {r.index}: start {r.start_t:.2f}s  bottom {r.bottom_t:.2f}s  "
              f"end {r.end_t:.2f}s  travel {r.depth_travel_px:.0f}px  conf={r.confidence}")

    # Sagittal-view gate signal.
    sep_hip = np.nanmedian(np.abs(track.both_hips_x[:, 0] - track.both_hips_x[:, 1]))
    sep_sh = np.nanmedian(np.abs(track.both_shoulders_x[:, 0] - track.both_shoulders_x[:, 1]))
    torso = np.nanmedian(np.linalg.norm(track.xy["shoulder"] - track.xy["hip"], axis=1))
    print(f"\nsagittal check: hip sep {sep_hip:.0f}px, shoulder sep {sep_sh:.0f}px, "
          f"torso {torso:.0f}px -> ratio {max(sep_hip, sep_sh) / torso:.3f} (small = side-on)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
