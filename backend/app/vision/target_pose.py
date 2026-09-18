"""Solve for the document-compliant pose, using the athlete's own body.

A canned animation of a "correct squat" would be generic reference content: the same clip for
every user, derived from nothing they did. The document is explicit that depth is defined by
*their* hip relative to *their* patella, and the back angle by *their* torso. So instead of
showing an idealised lifter, we solve a small inverse-kinematics problem constrained by this
athlete's measured segment lengths and the criteria their repetition actually failed.

The result is drawn as a ghost on their own bottom frame: here is where your hip was, here is
where it needed to be, and the distance between them is the correction.

Two honest limits, both surfaced to the user:
  * This is 2D. We never measured depth, so we do not render a third dimension we cannot see.
  * Only criteria that a side view can assess are corrected. The ghost says nothing about
    knees-out or stance, because the camera cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.optimize import least_squares

from .pose import PoseTrack
from .reps import Rep
from .smoothing import interpolate_gaps, smooth

# How far below the knee the target hip sits, in shin-lengths. The document's standard is
# geometric - hip below the top of the patella - and states no margin. This is ours: far enough
# past the measurement tolerance that the target is unambiguously compliant rather than
# borderline. Labelled engineering_tolerance everywhere it surfaces.
TARGET_DEPTH_MARGIN_SHIN = 0.06


@dataclass
class TargetPose:
    """Joint positions, in the same pixel space as the video frame."""

    frame: int
    t: float
    ankle: list[float]
    knee: list[float]
    hip: list[float]
    shoulder: list[float]
    bar: list[float] | None
    corrections: list[dict]
    solved: bool
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _seg_len(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def solve_target_pose(
    track: PoseTrack,
    rep: Rep,
    bar,
    failed_criteria: set[str],
    back_angle_reference: float,
    knee_forward_limit: float = 0.5,
) -> TargetPose | None:
    """Return the nearest pose satisfying the failed criteria, or None if not solvable.

    Fixed: the ankle (the foot is planted) and every segment length (they are bones).
    Free: the shank angle and the femur angle.
    Constrained: hip below knee by the target margin, and the torso at the document's
    reference back angle.
    """
    f = rep.bottom_frame
    sm = {j: smooth(interpolate_gaps(track.joint(j)), track.fps) for j
          in ("shoulder", "hip", "knee", "ankle", "heel", "toe")}
    P = {j: sm[j][f] for j in sm}

    if any(not np.all(np.isfinite(P[j])) for j in ("shoulder", "hip", "knee", "ankle")):
        return None

    shin = track.shin_length_px()
    if not np.isfinite(shin) or shin <= 0:
        return None

    tibia = _seg_len(P["ankle"], P["knee"])
    femur = _seg_len(P["knee"], P["hip"])
    torso = _seg_len(P["hip"], P["shoulder"])
    if min(tibia, femur, torso) < 1e-3:
        return None

    ankle = P["ankle"].copy()
    # Which way the athlete faces, from the foot. The torso leans this way.
    facing = float(np.sign(P["toe"][0] - P["heel"][0])) or 1.0

    # Current angles as the starting guess, so the solver returns the *nearest* compliant pose
    # rather than an arbitrary one - the correction shown is the smallest one that works.
    theta0 = float(np.arctan2(P["knee"][1] - ankle[1], P["knee"][0] - ankle[0]))
    phi0 = float(np.arctan2(P["hip"][1] - P["knee"][1], P["hip"][0] - P["knee"][0]))

    fix_depth = "depth" in failed_criteria
    target_hip_below = TARGET_DEPTH_MARGIN_SHIN * shin

    def forward(params):
        theta, phi = params
        knee = ankle + tibia * np.array([np.cos(theta), np.sin(theta)])
        hip = knee + femur * np.array([np.cos(phi), np.sin(phi)])
        return knee, hip

    midfoot_x = (P["heel"][0] + P["toe"][0]) / 2.0
    toe_x = P["toe"][0]

    def residuals(params):
        knee, hip = forward(params)
        res = []
        if fix_depth:
            # y grows downward: hip below knee means hip.y - knee.y > 0.
            res.append(((hip[1] - knee[1]) - target_hip_below) / shin)
        else:
            res.append(((hip[1] - knee[1]) - (P["hip"][1] - P["knee"][1])) / shin)

        # Keep the hip roughly above the foot: a real squat stays balanced over the midfoot.
        res.append(0.35 * (hip[0] - midfoot_x) / shin)

        # Do not fix one criterion by breaking another. Deepening the squat with a planted foot
        # drives the knee forward, and an unconstrained solve pushed it to 0.35 shin-lengths past
        # the toe on the common sample - past 'just a little forward of the toes' (ref p.23) and
        # toward failing a criterion this repetition was passing. A one-sided penalty keeps the
        # knee inside its own tolerance without pulling it back when it is already fine.
        knee_past_toe = (knee[0] - toe_x) * facing / shin
        if knee_past_toe > knee_forward_limit:
            res.append(2.0 * (knee_past_toe - knee_forward_limit))
        else:
            res.append(0.0)

        # Stay near the observed pose so the correction is minimal.
        res.append(0.25 * (params[0] - theta0))
        res.append(0.25 * (params[1] - phi0))
        return res

    sol = least_squares(residuals, x0=[theta0, phi0], max_nfev=400)
    knee_t, hip_t = forward(sol.x)

    # Torso: place the shoulder at the document's reference back angle, leaning the way the
    # athlete faces. Only moved if the back angle was among the failures.
    if "back_angle" in failed_criteria:
        ang = np.radians(back_angle_reference)
        shoulder_t = hip_t + torso * np.array([facing * np.cos(ang), -np.sin(ang)])
    else:
        shoulder_t = hip_t + (P["shoulder"] - P["hip"])

    # The bar rides with the shoulder.
    bar_t = None
    if bar is not None and np.isfinite(bar.x[f]):
        bar_t = (shoulder_t + (np.array([bar.x[f], bar.y[f]]) - P["shoulder"])).tolist()

    corrections: list[dict] = []
    if fix_depth:
        got = (P["hip"][1] - P["knee"][1]) / shin
        want = target_hip_below / shin
        where = ("below" if got > 0 else "above")
        corrections.append({
            "criterion_id": "depth",
            "label": "Sit lower",
            "detail": (
                f"At the bottom your hip was {abs(got):.2f} shin-lengths {where} your knee - "
                f"close enough to level that we could not call it either way. The ghost shows "
                f"the hip {want:.2f} below the knee, clearly past parallel. Because your foot "
                f"stays planted and your bones do not change length, reaching it means the whole "
                f"hip travels about {abs(hip_t[1] - P['hip'][1]) / shin:.2f} shin-lengths further "
                f"down and the shin angles further forward."
            ),
            "provenance": "document_stated rule, engineering_tolerance margin",
        })
    if "back_angle" in failed_criteria:
        cur = np.degrees(np.arctan2(abs(P["shoulder"][1] - P["hip"][1]),
                                    abs(P["shoulder"][0] - P["hip"][0])))
        corrections.append({
            "criterion_id": "back_angle",
            "label": "Change torso angle",
            "detail": (f"Your back was {cur:.0f} degrees from horizontal; the document's "
                       f"reference is about {back_angle_reference:.0f}."),
            "provenance": "document_stated",
        })

    return TargetPose(
        frame=f,
        t=rep.bottom_t,
        ankle=ankle.tolist(),
        knee=knee_t.tolist(),
        hip=hip_t.tolist(),
        shoulder=shoulder_t.tolist(),
        bar=bar_t,
        corrections=corrections,
        solved=bool(sol.success),
        note=None if sol.success else "The target pose solver did not fully converge.",
    )
