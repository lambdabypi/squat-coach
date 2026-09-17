"""Experiment: does locking the plate radius across the video kill the false positives?

The naive per-frame HoughCircles reported 5/5 'hits' on the common sample, but visual
inspection showed 3 of those were spurious large circles. The plate's apparent radius is
near-constant for a fixed camera, so: sample many frames, take the modal radius, then
re-detect inside a tight band around it.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


def circles_in(frame, min_r, max_r, min_dist_frac=0.15):
    h, w = frame.shape[:2]
    gray = cv2.medianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 5)
    c = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(min_dist_frac * w), param1=120, param2=60,
        minRadius=int(min_r), maxRadius=int(max_r),
    )
    return [] if c is None else np.round(c[0]).astype(int).tolist()


def darkness(frame, x, y, r):
    """Mean intensity inside the circle. A loaded plate is dark; ceiling gaps are not."""
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (int(x), int(y)), max(1, int(r * 0.6)), 255, -1)
    return cv2.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), mask=mask)[0]


def main() -> int:
    video = Path(sys.argv[1])
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    short = min(w, h)

    # Pass 1: wide net over many frames, keep only dark circles.
    radii = []
    for idx in range(0, total, 4):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        for x, y, r in circles_in(frame, 0.05 * short, 0.30 * short):
            if darkness(frame, x, y, r) < 90:       # plates are dark
                radii.append(r)

    if not radii:
        print("FAIL: no dark circles at all")
        return 1

    # Modal radius, bucketed to 5px.
    buckets = Counter(int(r // 5) * 5 for r in radii)
    modal = buckets.most_common(1)[0][0] + 2
    print(f"dark-circle radii: n={len(radii)} median={int(np.median(radii))} modal={modal}")
    print(f"top buckets: {buckets.most_common(5)}")

    # Pass 2: locked band.
    lo, hi = modal * 0.85, modal * 1.15
    hits, miss = 0, 0
    xs, ys, rs = [], [], []
    for idx in range(0, total, 4):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        cands = [c for c in circles_in(frame, lo, hi) if darkness(frame, *c) < 90]
        if cands:
            hits += 1
            x, y, r = cands[0]
            xs.append(x); ys.append(y); rs.append(r)
        else:
            miss += 1
    cap.release()

    n = hits + miss
    print(f"locked band [{lo:.0f},{hi:.0f}] -> {hits}/{n} frames ({100*hits/n:.0f}%)")
    print(f"radius spread: min={min(rs)} max={max(rs)} std={np.std(rs):.1f}")
    print(f"bar x spread : min={min(xs)} max={max(xs)} std={np.std(xs):.1f}  (should be SMALL: vertical path)")
    print(f"bar y range  : min={min(ys)} max={max(ys)} (should be LARGE: the squat)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
