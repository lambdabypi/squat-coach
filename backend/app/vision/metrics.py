"""Measurements, one function per `measure.id` in the skill.

Every number that reaches the user originates here. The agent is given these values and may
judge and explain them; it may not compute them. That separation is what makes a finding
checkable against the video.

Two fields carry the honesty requirements:
  * `basis` - 'observed' (measured from tracked pixels) vs 'estimated' (derived or inferred).
  * `available` / `reason` - an unavailable measurement names the occluded landmark rather
    than returning a number nobody should trust.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, Literal

import numpy as np

from .bar import BarTrack
from .pose import VISIBILITY_FLOOR, PoseTrack
from .reps import Rep
from .smoothing import angle_from_horizontal, interpolate_gaps, smooth

HIP_DRIVE_WINDOW_S = 0.15   # engineering choice; the document says "out of the bottom"
MIN_RISE_SHIN = 0.02        # minimum shoulder rise for a hip-drive ratio to mean anything


@dataclass
class Measurement:
    measure_id: str
    value: float | None
    unit: str
    basis: Literal["observed", "estimated"]
    frame: int | None
    t: float | None
    available: bool
    confidence: Literal["high", "medium", "low"]
    reason: str | None = None          # why unavailable, or what degrades it
    detail: dict | None = None         # supporting numbers for the explanation

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.value is not None:
            d["value"] = round(float(self.value), 4)
        if self.t is not None:
            d["t"] = round(float(self.t), 3)
        return d


def _unavailable(measure_id: str, unit: str, reason: str, frame: int | None = None) -> Measurement:
    return Measurement(measure_id, None, unit, "observed", frame, None, False, "low", reason)


def _require(track: PoseTrack, joints: list[str], frame: int) -> str | None:
    """Return a human reason if any required landmark is not reliably visible."""
    missing = [j for j in joints if not track.visible(j, frame)]
    if missing:
        names = ", ".join(missing)
        return (f"the {names} landmark{'s were' if len(missing) > 1 else ' was'} not reliably "
                f"visible at this frame (visibility below {VISIBILITY_FLOOR})")
    return None


# --------------------------------------------------------------------------- depth

def hip_minus_knee_y_at_bottom(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    f = rep.bottom_frame
    mid = "hip_minus_knee_y_at_bottom"
    if (reason := _require(track, ["hip", "knee"], f)):
        return _unavailable(mid, "shin_lengths", reason, f)
    shin = track.shin_length_px()
    hip_y, knee_y = track.y("hip")[f], track.y("knee")[f]
    value = (hip_y - knee_y) / shin          # >0 means hip is lower than knee
    return Measurement(
        mid, value, "shin_lengths", "observed", f, rep.bottom_t, True,
        "high" if rep.confidence == "high" else "medium",
        detail={
            "hip_y_px": round(float(hip_y), 1),
            "knee_y_px": round(float(knee_y), 1),
            "shin_px": round(shin, 1),
            "note": "Positive means the hip landmark is below the knee landmark.",
        },
    )


# ----------------------------------------------------------------------- back angle

def torso_angle_from_horizontal_at_bottom(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    f = rep.bottom_frame
    mid = "torso_angle_from_horizontal_at_bottom"
    if (reason := _require(track, ["shoulder", "hip"], f)):
        return _unavailable(mid, "degrees", reason, f)
    sh = smooth(interpolate_gaps(track.joint("shoulder")), track.fps)[f]
    hp = smooth(interpolate_gaps(track.joint("hip")), track.fps)[f]
    angle = float(angle_from_horizontal(hp, sh))
    return Measurement(
        mid, angle, "degrees", "observed", f, rep.bottom_t, True, "high",
        detail={
            "shoulder_px": [round(float(v), 1) for v in sh],
            "hip_px": [round(float(v), 1) for v in hp],
            "note": "0 degrees is horizontal, 90 is vertical.",
        },
    )


# ------------------------------------------------------------------------ hip drive

def hip_vs_shoulder_rise_ratio_early_ascent(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    mid = "hip_vs_shoulder_rise_ratio_early_ascent"
    lo, hi = rep.ascent_window(HIP_DRIVE_WINDOW_S)
    if hi - lo < 2:
        return _unavailable(mid, "ratio", "the ascent was too short to measure hip drive", lo)
    if (reason := _require(track, ["hip", "shoulder"], lo)):
        return _unavailable(mid, "ratio", reason, lo)

    hip_y = smooth(interpolate_gaps(track.y("hip")), track.fps)
    sh_y = smooth(interpolate_gaps(track.y("shoulder")), track.fps)
    hip_rise = float(hip_y[lo] - hip_y[hi])      # y decreases upward, so rise is positive
    sh_rise = float(sh_y[lo] - sh_y[hi])
    shin = track.shin_length_px()

    # A ratio is only meaningful when the denominator is a real movement. Guarding at 1e-6 px
    # let noise through and produced a ratio of -8.96 on the common sample, reported as a
    # confident failure. The floor is now a fraction of the athlete's own shin length.
    min_rise = MIN_RISE_SHIN * shin
    if sh_rise < min_rise:
        return _unavailable(
            mid, "ratio",
            (f"the shoulders rose less than {MIN_RISE_SHIN:.2f} shin-lengths in the first "
             f"{HIP_DRIVE_WINDOW_S * 1000:.0f} ms of the ascent, which is too little movement to "
             "compare hip and shoulder rise reliably"),
            lo,
        )
    if hip_rise < 0:
        return Measurement(
            mid, 0.0, "ratio", "observed", lo, lo / track.fps, True, "medium",
            reason="The hips did not rise at all in the early ascent.",
            detail={"hip_rise_shin": round(hip_rise / shin, 4),
                    "shoulder_rise_shin": round(sh_rise / shin, 4),
                    "note": "Hip rise was negative; reported as a ratio of 0."},
        )

    ratio = hip_rise / sh_rise
    return Measurement(
        mid, ratio, "ratio", "observed", lo, lo / track.fps, True, "medium",
        detail={
            "window_s": HIP_DRIVE_WINDOW_S,
            "hip_rise_shin": round(hip_rise / shin, 4),
            "shoulder_rise_shin": round(sh_rise / shin, 4),
            "note": "Ratio >= 1 means the hips rose at least as fast as the shoulders.",
        },
    )


# ---------------------------------------------------------------- knee versus toe

def knee_x_minus_toe_x_at_bottom(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    f = rep.bottom_frame
    mid = "knee_x_minus_toe_x_at_bottom"
    if (reason := _require(track, ["knee", "toe", "heel"], f)):
        return _unavailable(mid, "shin_lengths", reason, f)
    shin = track.shin_length_px()
    knee_x, toe_x, heel_x = track.x("knee")[f], track.x("toe")[f], track.x("heel")[f]
    facing = np.sign(toe_x - heel_x) or 1.0     # +1 if the athlete faces +x
    value = float((knee_x - toe_x) * facing / shin)
    return Measurement(
        mid, value, "shin_lengths", "observed", f, rep.bottom_t, True, "medium",
        detail={
            "knee_x_px": round(float(knee_x), 1),
            "toe_x_px": round(float(toe_x), 1),
            "facing": "+x" if facing > 0 else "-x",
            "note": "Positive means the knee is forward of the toe in the direction the athlete faces.",
        },
    )


# ----------------------------------------------------------------------- heels flat

def heel_vertical_displacement(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    mid = "heel_vertical_displacement"
    f = rep.bottom_frame
    if (reason := _require(track, ["heel"], f)):
        return _unavailable(mid, "shin_lengths", reason, f)
    heel_y = smooth(interpolate_gaps(track.y("heel")), track.fps)
    standing = heel_y[rep.start_frame]
    if not np.isfinite(standing):
        return _unavailable(mid, "shin_lengths", "the heel was not visible while standing", f)
    shin = track.shin_length_px()
    rise = float((standing - heel_y[f]) / shin)  # positive means the heel came up
    return Measurement(
        mid, rise, "shin_lengths", "observed", f, rep.bottom_t, True, "medium",
        reason="Heel landmarks are easily confused by footwear and by the far foot.",
        detail={"standing_heel_y_px": round(float(standing), 1),
                "bottom_heel_y_px": round(float(heel_y[f]), 1)},
    )


# -------------------------------------------------------------------------- gaze

def head_pitch_proxy(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    mid = "head_pitch_proxy"
    f = rep.bottom_frame
    if (reason := _require(track, ["ear", "nose"], f)):
        return _unavailable(mid, "degrees", reason, f)
    ear, nose = track.joint("ear")[f], track.joint("nose")[f]

    # MediaPipe reports full visibility for head landmarks even when the head is entirely
    # hidden behind the plate - it is in the common sample, and the first version of this
    # returned a confident "looking down" from landmarks nobody can see. If the head falls
    # inside the detected plate, the pose model is inferring, not observing.
    if bar is not None and bar.any_tracked and np.isfinite(bar.median_radius):
        if bar.basis_observed[f] and np.isfinite(bar.x[f]):
            d = float(np.hypot(nose[0] - bar.x[f], nose[1] - bar.y[f]))
            if d < bar.median_radius:
                return _unavailable(
                    mid, "degrees",
                    ("the head is behind the barbell plate in this frame, so head orientation is "
                     "inferred by the pose model rather than observed"),
                    f,
                )

    # Positive = nose below ear = head pitched down.
    pitch = float(np.degrees(np.arctan2(nose[1] - ear[1], abs(nose[0] - ear[0]) + 1e-6)))
    return Measurement(
        mid, pitch, "degrees", "estimated", f, rep.bottom_t, True, "low",
        reason=("Head orientation is a proxy for gaze; the eyes are not observable and the head "
                "is often occluded by the plate in a side view."),
        detail={"note": "Positive degrees means the nose sits below the ear, i.e. head pitched down."},
    )


# ------------------------------------------------------------------ bar-dependent

def max_bar_horizontal_deviation_from_midfoot(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    mid = "max_bar_horizontal_deviation_from_midfoot"
    if bar is None or not bar.any_tracked:
        return _unavailable(mid, "shin_lengths", "the barbell could not be located in this video")
    if (reason := _require(track, ["heel", "toe"], rep.bottom_frame)):
        return _unavailable(mid, "shin_lengths", reason, rep.bottom_frame)

    lo, hi = rep.start_frame, rep.end_frame
    shin = track.shin_length_px()
    heel_x = interpolate_gaps(track.x("heel"))[lo:hi + 1]
    toe_x = interpolate_gaps(track.x("toe"))[lo:hi + 1]
    midfoot_x = (heel_x + toe_x) / 2.0                      # document: halfway along the sole
    bar_x = bar.x[lo:hi + 1]
    ok = np.isfinite(bar_x) & np.isfinite(midfoot_x)
    if ok.sum() < 3:
        return _unavailable(mid, "shin_lengths", "the barbell was not tracked during this repetition")

    dev = np.abs(bar_x[ok] - midfoot_x[ok]) / shin
    j = int(np.argmax(dev))
    frame = lo + int(np.flatnonzero(ok)[j])
    observed_frac = float(np.mean(bar.basis_observed[lo:hi + 1]))
    basis = "observed" if observed_frac >= 0.5 else "estimated"
    return Measurement(
        mid, float(dev.max()), "shin_lengths", basis, frame, frame / track.fps, True,
        "high" if observed_frac > 0.8 else "medium" if observed_frac >= 0.5 else "low",
        reason=None if basis == "observed" else
        ("The bar position is a shoulder-offset estimate for most of this repetition because the "
         "plate could not be detected; treat the bar path as indicative, not measured."),
        detail={
            "tracked_fraction": round(observed_frac, 2),
            "worst_deviation_shin": round(float(dev.max()), 4),
            "note": "Midfoot is the midpoint between heel and toe landmarks.",
        },
    )


def bar_y_relative_to_shoulder(track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    mid = "bar_y_relative_to_shoulder"
    if bar is None or not bar.any_tracked:
        return _unavailable(mid, "shin_lengths", "the barbell could not be located in this video")
    f = rep.start_frame
    if (reason := _require(track, ["shoulder"], f)):
        return _unavailable(mid, "shin_lengths", reason, f)
    if not np.isfinite(bar.y[f]):
        return _unavailable(mid, "shin_lengths", "the barbell was not tracked at the top of this repetition", f)
    shin = track.shin_length_px()
    value = float((bar.y[f] - track.y("shoulder")[f]) / shin)
    return Measurement(
        mid, value, "shin_lengths", "observed" if bar.basis_observed[f] else "estimated",
        f, f / track.fps, True, "low",
        reason=("There is no scapular-spine landmark in pose estimation, and correct versus "
                "incorrect bar placement differs by roughly two centimetres on the athlete."),
        detail={"note": "Positive means the bar centre sits below the shoulder landmark."},
    )


# --------------------------------------------------------------------------- registry

MEASURES: dict[str, Callable[[PoseTrack, Rep, BarTrack | None], Measurement]] = {
    "hip_minus_knee_y_at_bottom": hip_minus_knee_y_at_bottom,
    "torso_angle_from_horizontal_at_bottom": torso_angle_from_horizontal_at_bottom,
    "hip_vs_shoulder_rise_ratio_early_ascent": hip_vs_shoulder_rise_ratio_early_ascent,
    "knee_x_minus_toe_x_at_bottom": knee_x_minus_toe_x_at_bottom,
    "heel_vertical_displacement": heel_vertical_displacement,
    "head_pitch_proxy": head_pitch_proxy,
    "max_bar_horizontal_deviation_from_midfoot": max_bar_horizontal_deviation_from_midfoot,
    "bar_y_relative_to_shoulder": bar_y_relative_to_shoulder,
}


def compute(measure_id: str, track: PoseTrack, rep: Rep, bar: BarTrack | None) -> Measurement:
    fn = MEASURES.get(measure_id)
    if fn is None:
        raise KeyError(f"skill references measure '{measure_id}' which the vision layer does not implement")
    return fn(track, rep, bar)
