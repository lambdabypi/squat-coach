"""Global quality gates.

These run before any criterion is judged. Their job is to decide what the video is *capable* of
supporting, so that the assessment never reaches further than the evidence does.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .bar import BarTrack
from .pose import PoseTrack
from .reps import RepSegmentation

# Engineering thresholds, mirrored in the skill's global_gates block.
SAGITTAL_RATIO_OK = 0.25       # max(hip,shoulder) L-R separation / torso length
SAGITTAL_RATIO_MARGINAL = 0.40
MIN_DETECTION_FRACTION = 0.7
EDGE_MARGIN_FRAC = 0.02        # landmark within 2% of a frame edge counts as clipped


@dataclass
class Gate:
    id: str
    passed: bool
    severity: str              # ok | degraded | blocking
    detail: str
    value: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.value is not None:
            d["value"] = round(float(self.value), 4)
        return d


@dataclass
class QualityReport:
    gates: list[Gate]
    view_ratio: float
    detection_fraction: float
    feet_in_frame: bool
    bar_in_frame: bool

    @property
    def blocking(self) -> list[Gate]:
        return [g for g in self.gates if not g.passed and g.severity == "blocking"]

    @property
    def is_assessable(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict:
        return {
            "gates": [g.to_dict() for g in self.gates],
            "view_ratio": round(self.view_ratio, 4),
            "detection_fraction": round(self.detection_fraction, 3),
            "feet_in_frame": self.feet_in_frame,
            "bar_in_frame": self.bar_in_frame,
            "is_assessable": self.is_assessable,
            "blocking_reasons": [g.detail for g in self.blocking],
        }


def _view_ratio(track: PoseTrack) -> float:
    """How far apart the left and right landmarks sit horizontally, relative to torso length.

    A true side view collapses left onto right. A front view separates them by shoulder width.
    """
    hip_sep = np.nanmedian(np.abs(track.both_hips_x[:, 0] - track.both_hips_x[:, 1]))
    sh_sep = np.nanmedian(np.abs(track.both_shoulders_x[:, 0] - track.both_shoulders_x[:, 1]))
    torso = np.nanmedian(np.linalg.norm(track.xy["shoulder"] - track.xy["hip"], axis=1))
    if not np.isfinite(torso) or torso <= 0:
        return float("nan")
    return float(max(hip_sep, sh_sep) / torso)


def assess_quality(track: PoseTrack, seg: RepSegmentation, bar: BarTrack | None) -> QualityReport:
    gates: list[Gate] = []

    # Detection quality is computed first: the camera-angle test is derived from landmark
    # positions, so when the person is barely detected the angle estimate is meaningless.
    # An earlier version asserted "this is not a side view" for a video that was simply too
    # dark and badly cropped — a confident diagnosis from unreliable inputs, which is exactly
    # the failure this gate exists to prevent.
    det = float(track.detected.mean()) if track.detected is not None else 0.0

    # 1. Sagittal view ------------------------------------------------------
    ratio = _view_ratio(track)
    if det < MIN_DETECTION_FRACTION:
        gates.append(Gate("sagittal_view", True, "degraded",
                          "The camera angle could not be checked reliably because the athlete was "
                          "detected in too few frames. Fix the lighting and framing first.", ratio))
    elif not np.isfinite(ratio):
        gates.append(Gate("sagittal_view", False, "blocking",
                          "The camera angle could not be determined from the landmarks.", None))
    elif ratio <= SAGITTAL_RATIO_OK:
        gates.append(Gate("sagittal_view", True, "ok",
                          "The camera is side-on to the athlete.", ratio))
    elif ratio <= SAGITTAL_RATIO_MARGINAL:
        gates.append(Gate("sagittal_view", True, "degraded",
                          "The camera is only roughly side-on. Angle measurements are less reliable "
                          "because the movement plane is foreshortened.", ratio))
    else:
        gates.append(Gate("sagittal_view", False, "blocking",
                          "This does not appear to be a side view. The reference document defines "
                          "squat depth on the profile view, so no criterion can be assessed from "
                          "this angle. Re-record with the camera directly to one side.", ratio))

    # 2. Person detected ----------------------------------------------------
    if det >= MIN_DETECTION_FRACTION:
        gates.append(Gate("person_detected", True, "ok",
                          f"A person was detected in {det:.0%} of frames.", det))
    elif det > 0.3:
        gates.append(Gate("person_detected", True, "degraded",
                          f"A person was detected in only {det:.0%} of frames; parts of the "
                          "movement are missing.", det))
    else:
        gates.append(Gate("person_detected", False, "blocking",
                          f"A person was detected in only {det:.0%} of frames. The subject may be "
                          "too small in frame, too dark, or obscured.", det))

    # 3. A repetition exists ------------------------------------------------
    if seg.reps:
        gates.append(Gate("rep_detected", True, "ok",
                          f"{len(seg.reps)} repetition(s) identified.", float(len(seg.reps))))
    else:
        gates.append(Gate("rep_detected", False, "blocking",
                          seg.note or "No complete repetition was found in this video."))

    # 4. Framing ------------------------------------------------------------
    h, w = track.height, track.width
    mx, my = EDGE_MARGIN_FRAC * w, EDGE_MARGIN_FRAC * h

    def in_frame(joint: str) -> float:
        p = track.xy[joint]
        ok = np.isfinite(p[:, 0]) & (p[:, 0] > mx) & (p[:, 0] < w - mx) \
            & (p[:, 1] > my) & (p[:, 1] < h - my)
        return float(ok.mean())

    feet_frac = min(in_frame("heel"), in_frame("toe"))
    feet_in_frame = feet_frac > 0.8
    gates.append(Gate(
        "feet_in_frame", feet_in_frame, "ok" if feet_in_frame else "degraded",
        "Both feet are in frame." if feet_in_frame else
        f"The feet leave the frame in {1 - feet_frac:.0%} of frames. Bar-path and knee-position "
        "criteria depend on the foot landmarks and will abstain where they are missing.",
        feet_frac,
    ))

    bar_in_frame = True
    if bar is not None and bar.any_tracked:
        bx, by = bar.x, bar.y
        ok = np.isfinite(bx) & (bx > 0) & (bx < w) & (by > 0) & (by < h)
        bar_frac = float(ok.mean())
        bar_in_frame = bar_frac > 0.8
        if bar.observed_fraction >= 0.5:
            gates.append(Gate("bar_tracked", True,
                              "ok" if bar.observed_fraction > 0.8 else "degraded",
                              f"The barbell plate was detected in {bar.observed_fraction:.0%} of frames."
                              + (f" {bar.note}" if bar.note else ""),
                              bar.observed_fraction))
        else:
            gates.append(Gate("bar_tracked", False, "degraded",
                              f"The barbell plate was detected in only {bar.observed_fraction:.0%} of "
                              "frames. Bar position is estimated from the shoulder for the rest, so "
                              "bar-path findings are indicative rather than measured.",
                              bar.observed_fraction))
    else:
        gates.append(Gate("bar_tracked", False, "degraded",
                          "No barbell plate was detected. Bar-path and bar-placement criteria "
                          "cannot be assessed from tracked pixels.", 0.0))

    return QualityReport(
        gates=gates,
        view_ratio=ratio,
        detection_fraction=det,
        feet_in_frame=feet_in_frame,
        bar_in_frame=bar_in_frame,
    )
