"""Repetition segmentation from the hip height signal.

In image coordinates y grows downward, so the bottom of a squat is a *maximum* of hip y.
Reps are found as prominent maxima, with the standing positions either side taken as the
boundaries.

The prominence floor is expressed as a fraction of the observed hip travel rather than in
pixels, so it adapts to framing and to how deep the athlete actually goes. It is an
engineering choice and is not a document requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from .pose import PoseTrack
from .smoothing import interpolate_gaps, smooth, velocity

MIN_PROMINENCE_FRAC = 0.25   # of total hip travel
MIN_REP_SEPARATION_S = 0.6
MIN_DESCENT_TRAVEL_FRAC = 0.20

# Where a repetition really begins and ends, as a fraction of its own descent below standing.
#
# Taking the bounding hip-height troughs was wrong on any clip that shows the un-rack. Lifting a
# loaded bar off the pins raises the hips *above* standing, so the un-rack is a trough, and so is
# the re-rack. On a real gym clip that made repetition 1 start 5 seconds early: a 156-frame
# "descent" that was mostly the walk-out and setup, and a 34-frame ascent. Metrics measured over
# that window picked up the walk-out - bar path is a max-deviation measurement, so walking
# sideways out of the rack guaranteed a large one, and the heels-flat reference frame was taken
# while the heel was still raised from the un-rack.
#
# The tightened boundary is the frame where the hip has descended this far past standing, which is
# unambiguously the lift rather than the setup.
MOVEMENT_ONSET_FRAC = 0.15
# Percentile of hip height taken as the athlete's standing level. Not the minimum: a few frames of
# un-rack sit above standing and would drag the reference with them.
STANDING_PERCENTILE = 15.0


@dataclass
class Rep:
    index: int                  # 1-based, as shown to the user
    start_frame: int            # top of the descent
    bottom_frame: int           # the frame most criteria are measured at
    end_frame: int              # top of the ascent
    fps: float
    depth_travel_px: float      # hip travel from top to bottom
    confidence: str             # high | medium | low

    @property
    def start_t(self) -> float:
        return self.start_frame / self.fps

    @property
    def bottom_t(self) -> float:
        return self.bottom_frame / self.fps

    @property
    def end_t(self) -> float:
        return self.end_frame / self.fps

    def ascent_window(self, seconds: float) -> tuple[int, int]:
        """Frames covering the first `seconds` of the ascent - the hip-drive window."""
        lo = self.bottom_frame
        hi = min(self.end_frame, lo + max(2, int(round(seconds * self.fps))))
        return lo, hi

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start_frame": self.start_frame,
            "bottom_frame": self.bottom_frame,
            "end_frame": self.end_frame,
            "start_t": round(self.start_t, 3),
            "bottom_t": round(self.bottom_t, 3),
            "end_t": round(self.end_t, 3),
            "confidence": self.confidence,
        }


@dataclass
class RepSegmentation:
    reps: list[Rep]
    hip_y_smooth: np.ndarray
    hip_y_velocity: np.ndarray
    note: str | None = None


def segment_reps(track: PoseTrack) -> RepSegmentation:
    hip_y = interpolate_gaps(track.y("hip"))
    hip_y_s = smooth(hip_y, track.fps)
    vel = velocity(hip_y_s, track.fps)

    finite = hip_y_s[np.isfinite(hip_y_s)]
    if finite.size < 5:
        return RepSegmentation([], hip_y_s, vel, "Hip landmarks were never reliably visible.")

    travel = float(np.nanmax(finite) - np.nanmin(finite))
    if travel < 1.0:
        return RepSegmentation([], hip_y_s, vel, "The hips barely moved; no repetition was found.")

    work = np.nan_to_num(hip_y_s, nan=np.nanmin(finite))
    peaks, props = find_peaks(
        work,
        prominence=MIN_PROMINENCE_FRAC * travel,
        distance=max(1, int(round(MIN_REP_SEPARATION_S * track.fps))),
    )

    if len(peaks) == 0:
        return RepSegmentation([], hip_y_s, vel,
                               "No bottom position was found. The clip may not contain a full repetition.")

    # Troughs (standing positions) bound each rep.
    troughs, _ = find_peaks(-work, prominence=MIN_PROMINENCE_FRAC * travel * 0.5)
    troughs = np.concatenate(([0], troughs, [len(work) - 1]))

    # The athlete's standing hip height, used to tell the lift apart from the setup around it.
    standing = float(np.nanpercentile(finite, STANDING_PERCENTILE))

    reps: list[Rep] = []
    for k, p in enumerate(peaks):
        before = troughs[troughs < p]
        after = troughs[troughs > p]
        start = int(before[-1]) if before.size else 0
        end = int(after[0]) if after.size else len(work) - 1
        # Kept for the clipped-at-the-edges check below: tightening moves start and end inward,
        # which would otherwise disguise a repetition running off the end of the clip as a
        # comfortably bounded one.
        raw_start, raw_end = start, end

        descent = float(work[p] - work[start])
        if descent < MIN_DESCENT_TRAVEL_FRAC * travel:
            continue  # a wobble, not a rep

        # Pull the boundaries in to where the hip is actually descending or rising, so the
        # un-rack, the setup and the re-rack are not measured as part of the repetition.
        onset = standing + MOVEMENT_ONSET_FRAC * max(0.0, float(work[p]) - standing)
        above = np.flatnonzero(work[start:p + 1] <= onset)
        if above.size:
            start = int(start + above[-1])
        below = np.flatnonzero(work[p:end + 1] <= onset)
        if below.size:
            end = int(p + below[0])

        # Recompute against the tightened start: depth_travel_px feeds rep confidence and the
        # overlay, and measuring it from a walk-out would overstate how far the hips travelled.
        descent = float(work[p] - work[start])
        if descent < MIN_DESCENT_TRAVEL_FRAC * travel:
            continue

        prom = float(props["prominences"][k])
        if prom > 0.6 * travel:
            conf = "high"
        elif prom > 0.35 * travel:
            conf = "medium"
        else:
            conf = "low"

        # A rep whose boundaries touch the clip edges may be clipped.
        if raw_start == 0 or raw_end == len(work) - 1:
            conf = "medium" if conf == "high" else "low"

        reps.append(Rep(
            index=len(reps) + 1,
            start_frame=start,
            bottom_frame=int(p),
            end_frame=end,
            fps=track.fps,
            depth_travel_px=descent,
            confidence=conf,
        ))

    note = None
    if not reps:
        note = "Movement was detected but no repetition was deep or complete enough to assess."
    elif len(reps) == 1:
        note = "Only one repetition was found; it may be a partial clip."
    return RepSegmentation(reps, hip_y_s, vel, note)
