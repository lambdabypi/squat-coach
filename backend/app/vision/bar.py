"""Barbell tracking.

A loaded plate in a sagittal view is a large, dark, near-circular blob at shoulder height, and
its apparent radius is nearly constant for a fixed camera. That is a lot of structure to exploit,
and the first version of this exploited none of it.

**What went wrong first, and why the design looks like this.** The initial detector ran
HoughCircles over a horizontal band around the shoulder but left the search unbounded across the
full frame width. On the common sample it reported a circle on 5 of 5 sampled frames and looked
like a success; three of those five were rack uprights, rig frames and ceiling gaps. The recorded
radii gave it away — 164, 306, 294, 306, 168 px — two clusters, when a plate can only produce one.

The obvious repair, locking onto the modal radius across the clip, failed too: spurious circles
*outnumbered* the plate 73 to 42, so the mode was the background. The tell was that bar x ranged
over 49-725 px in a 1080-wide frame, and a barbell path in a squat is close to vertical.

So the detector now:
  1. searches only a box anchored to the shoulder landmark and sized by the athlete's own torso,
  2. scores candidates on darkness, proximity to the shoulder and radius plausibility,
  3. rejects, after the fact, any detection whose radius departs from the clip median, and
  4. falls back to a shoulder-offset **estimate** that is labelled as such, never silently.

Anything this module cannot observe is marked `basis_observed = False`, and every measurement
derived from it inherits that label.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24

# All engineering choices; the reference document says nothing about pixels.
ROI_HALF_TORSO_MULT = 1.15      # search box half-width, in torso lengths
MIN_R_TORSO = 0.22              # plate radius bounds, in torso lengths
MAX_R_TORSO = 0.95
DARK_MAX_INTENSITY = 110        # a loaded plate is dark
RADIUS_CONSISTENCY_TOL = 0.22   # reject detections this far from the clip median radius
BAR_ABOVE_SHOULDER_PX = 0.0     # the bar sits essentially at the shoulder landmark height


@dataclass
class BarTrack:
    x: np.ndarray                 # (N,) pixels, NaN where unknown
    y: np.ndarray
    r: np.ndarray
    basis_observed: np.ndarray    # (N,) bool — True only where a plate was actually detected
    median_radius: float
    observed_fraction: float
    note: str | None = None

    @property
    def any_tracked(self) -> bool:
        return bool(np.isfinite(self.x).any())

    def to_overlay(self, fps: float) -> list[dict]:
        return [
            {
                "frame": int(i),
                "t": round(i / fps, 3),
                "x": None if not np.isfinite(self.x[i]) else round(float(self.x[i]), 1),
                "y": None if not np.isfinite(self.y[i]) else round(float(self.y[i]), 1),
                "observed": bool(self.basis_observed[i]),
            }
            for i in range(len(self.x))
        ]


class BarDetector:
    """Accumulates per-frame candidates during the single pose decode pass."""

    def __init__(self) -> None:
        self._x: list[float] = []
        self._y: list[float] = []
        self._r: list[float] = []
        self._obs: list[bool] = []
        self._shoulder: list[tuple[float, float]] = []
        self._torso: list[float] = []

    # -- called once per frame from extract_pose's frame_sink -------------------

    def feed(self, idx: int, frame: np.ndarray, lms) -> None:
        if lms is None:
            self._push(np.nan, np.nan, np.nan, False, (np.nan, np.nan), np.nan)
            return

        h, w = frame.shape[:2]
        sx = (lms[L_SHOULDER].x + lms[R_SHOULDER].x) / 2 * w
        sy = (lms[L_SHOULDER].y + lms[R_SHOULDER].y) / 2 * h
        hx = (lms[L_HIP].x + lms[R_HIP].x) / 2 * w
        hy = (lms[L_HIP].y + lms[R_HIP].y) / 2 * h
        torso = float(np.hypot(sx - hx, sy - hy))
        if not np.isfinite(torso) or torso < 10:
            self._push(np.nan, np.nan, np.nan, False, (sx, sy), torso)
            return

        best = self._detect(frame, (sx, sy), torso)
        if best is None:
            self._push(np.nan, np.nan, np.nan, False, (sx, sy), torso)
        else:
            bx, by, br = best
            self._push(bx, by, br, True, (sx, sy), torso)

    def _detect(self, frame, shoulder, torso):
        h, w = frame.shape[:2]
        sx, sy = shoulder
        half = ROI_HALF_TORSO_MULT * torso
        x0, x1 = int(max(0, sx - half)), int(min(w, sx + half))
        y0, y1 = int(max(0, sy - half)), int(min(h, sy + half))
        if x1 - x0 < 20 or y1 - y0 < 20:
            return None

        roi = frame[y0:y1, x0:x1]
        gray = cv2.medianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 5)
        min_r, max_r = int(MIN_R_TORSO * torso), int(MAX_R_TORSO * torso)
        if max_r <= min_r:
            return None

        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=int(max(10, 0.5 * torso)), param1=120, param2=55,
            minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            return None

        best, best_score = None, -1e9
        for cx, cy, cr in np.round(circles[0]).astype(int):
            gx, gy = cx + x0, cy + y0
            mask = np.zeros(gray.shape, np.uint8)
            cv2.circle(mask, (int(cx), int(cy)), max(1, int(cr * 0.6)), 255, -1)
            mean_i = cv2.mean(gray, mask=mask)[0]
            if mean_i > DARK_MAX_INTENSITY:
                continue
            # Closer to the shoulder and darker is better; both normalised to ~[0,1].
            dist = np.hypot(gx - sx, gy - sy) / torso
            score = (1.0 - min(dist, 2.0) / 2.0) * 1.5 + (1.0 - mean_i / 255.0)
            if score > best_score:
                best, best_score = (float(gx), float(gy), float(cr)), score
        return best

    def _push(self, x, y, r, obs, shoulder, torso):
        self._x.append(x); self._y.append(y); self._r.append(r)
        self._obs.append(obs); self._shoulder.append(shoulder); self._torso.append(torso)

    # -- called once after the pass --------------------------------------------

    def finalise(self) -> BarTrack:
        x = np.array(self._x, float)
        y = np.array(self._y, float)
        r = np.array(self._r, float)
        obs = np.array(self._obs, bool)
        sh = np.array(self._shoulder, float)
        torso = np.array(self._torso, float)
        n = len(x)

        note = None
        if obs.sum() >= 5:
            med_r = float(np.median(r[obs]))
            # A plate's apparent radius cannot change much. Anything that disagrees with the
            # clip median is something else in the gym, no matter how confident Hough was.
            bad = obs & (np.abs(r - med_r) / med_r > RADIUS_CONSISTENCY_TOL)
            x[bad] = y[bad] = r[bad] = np.nan
            obs[bad] = False
            if bad.sum():
                note = (f"{int(bad.sum())} frame(s) had a circle detected at an implausible radius "
                        f"and were discarded as background structure.")
        else:
            med_r = float("nan")

        observed_fraction = float(obs.mean()) if n else 0.0

        # Fall back to a shoulder-anchored estimate wherever the plate was not observed.
        # The bar rides on the back at shoulder height; this is a position estimate, not a
        # measurement, and every consumer sees basis_observed == False for these frames.
        if obs.any():
            offset = np.nanmedian((y[obs] - sh[obs, 1]))
            offset = 0.0 if not np.isfinite(offset) else float(offset)
        else:
            offset = BAR_ABOVE_SHOULDER_PX
            note = ("The barbell plate was never detected; bar position is estimated from the "
                    "shoulder landmark throughout and the bar path should be treated as indicative only.")

        missing = ~obs & np.isfinite(sh[:, 0])
        x[missing] = sh[missing, 0]
        y[missing] = sh[missing, 1] + offset

        return BarTrack(
            x=x, y=y, r=r,
            basis_observed=obs,
            median_radius=med_r,
            observed_fraction=observed_fraction,
            note=note,
        )
