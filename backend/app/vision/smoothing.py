"""Signal conditioning for landmark series.

Pose landmarks jitter by a few pixels frame to frame. Every measurement in the report is taken
from a smoothed series, and the smoothing window is deliberately short - long enough to kill
jitter, short enough not to round off the bottom of the rep, which is the single frame most of
the criteria are measured at.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

# Engineering choices, not document values.
SMOOTH_WINDOW_S = 0.20   # ~6 frames at 30fps
SAVGOL_ORDER = 2


def interpolate_gaps(a: np.ndarray, max_gap: int = 5) -> np.ndarray:
    """Fill short NaN runs by linear interpolation; leave long ones as NaN.

    A long gap means the landmark genuinely was not visible. Filling it would manufacture
    evidence, so it stays NaN and the criterion abstains.
    """
    a = np.asarray(a, dtype=float).copy()
    if a.ndim == 2:
        return np.stack([interpolate_gaps(a[:, c], max_gap) for c in range(a.shape[1])], axis=1)

    ok = ~np.isnan(a)
    if ok.sum() < 2:
        return a
    idx = np.arange(len(a))
    filled = np.interp(idx, idx[ok], a[ok])

    # Re-blank any gap longer than max_gap.
    out = filled.copy()
    run_start = None
    for i in range(len(a)):
        if not ok[i]:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start > max_gap:
                out[run_start:i] = np.nan
            run_start = None
    if run_start is not None and len(a) - run_start > max_gap:
        out[run_start:] = np.nan
    return out


def smooth(a: np.ndarray, fps: float, window_s: float = SMOOTH_WINDOW_S) -> np.ndarray:
    """Savitzky-Golay smoothing. Preserves peak shape better than a moving average,
    which matters because the bottom of the rep is a peak we measure at."""
    a = np.asarray(a, dtype=float)
    if a.ndim == 2:
        return np.stack([smooth(a[:, c], fps, window_s) for c in range(a.shape[1])], axis=1)

    win = int(round(window_s * fps))
    win = max(5, win | 1)                     # odd, at least 5
    if len(a) < win or np.isnan(a).all():
        return a
    ok = ~np.isnan(a)
    if not ok.all():
        # Smooth over the interpolated series, then restore the blanks.
        filled = interpolate_gaps(a, max_gap=len(a))
        sm = savgol_filter(filled, win, min(SAVGOL_ORDER, win - 1))
        sm[~ok] = np.nan
        return sm
    return savgol_filter(a, win, min(SAVGOL_ORDER, win - 1))


def velocity(a: np.ndarray, fps: float) -> np.ndarray:
    """First derivative in units per second."""
    return np.gradient(np.asarray(a, dtype=float)) * fps


def normalise(px: float | np.ndarray, shin_px: float) -> float | np.ndarray:
    """Convert a pixel distance to shin-lengths, the unit every reported distance uses."""
    if not np.isfinite(shin_px) or shin_px <= 0:
        return np.nan if np.isscalar(px) else np.full_like(np.asarray(px, dtype=float), np.nan)
    return px / shin_px


def angle_from_horizontal(p_from: np.ndarray, p_to: np.ndarray) -> np.ndarray:
    """Angle in degrees between the vector p_from->p_to and the horizontal, in [0, 90].

    Image coordinates have y increasing downward; we take the magnitude, so 90 means vertical
    and 0 means flat. This is the convention the document's 'back angle' uses: the angle
    between the plane of the torso and the floor.
    """
    v = np.asarray(p_to, dtype=float) - np.asarray(p_from, dtype=float)
    if v.ndim == 1:
        v = v[None, :]
    ang = np.degrees(np.arctan2(np.abs(v[:, 1]), np.abs(v[:, 0])))
    return ang if ang.size > 1 else float(ang[0])
