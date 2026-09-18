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

# How much more shin lean than the athlete demonstrated we are willing to ask for, in degrees.
# Small and deliberately so: the point of the limit is that the demonstrated lean is evidence of
# their range, and anything well past it is a guess. Labelled engineering_tolerance.
ANKLE_ALLOWANCE_DEG = 4.0

# How far behind the midfoot the target hip may sit, in shin-lengths. The hip is behind the foot
# in every real squat - that is what sitting back means - so this is a generous outer limit whose
# job is to stop the solver buying depth by tipping the athlete over, now that depth comes from
# the hips travelling back. A one-sided limit, not a pull toward the midfoot: the earlier pull
# was what forced the knees forward and produced an impossible shin angle.
BALANCE_LIMIT_SHIN = 0.60

# How much of the depth shortfall the target must actually close before we call it a target. Below
# this the solve has effectively failed and saying so is more use than a ghost in the wrong place.
MIN_DEPTH_PROGRESS = 0.6


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
    # True when a physical limit, not effort, is what stops the target reaching depth. The ghost
    # then shows the deepest position actually reachable, and limit_reason names what bound:
    # "ankle" (dorsiflexion beyond what they demonstrated), "balance" (hip past the point they
    # could hold), "ankle_and_balance", or "unknown" when the solve fell short for neither.
    depth_limited: bool = False
    limit_reason: str | None = None
    observed_shin_lean_deg: float | None = None
    target_shin_lean_deg: float | None = None
    hip_behind_midfoot_shin: float | None = None

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

    toe_x = P["toe"][0]
    midfoot_x = (P["heel"][0] + P["toe"][0]) / 2.0

    # The athlete's own demonstrated ankle range, measured from this video.
    #
    # This replaces a hip-over-midfoot pull that turned out to be the wrong constraint. That
    # term stopped the hips travelling BACK, so the only way left to gain depth was to drive
    # the knees FORWARD, and the solver duly asked for 55 degrees of shin lean against the 39
    # the athlete actually showed. Sixteen degrees of extra dorsiflexion is beyond even a shod
    # range: the heel would lift, breaking the document's feet-flat requirement (ref p.23), so
    # the target satisfied depth by quietly violating a different criterion.
    #
    # A population dorsiflexion figure would be a guess about this person. Their own deepest
    # observed shin lean, achieved with the heel down, is evidence. Allow a little more than
    # they showed and no more.
    observed_shin_lean = abs(np.degrees(np.arctan2(
        abs(P["knee"][0] - ankle[0]), abs(P["knee"][1] - ankle[1]),
    )))
    shin_lean_limit = observed_shin_lean + ANKLE_ALLOWANCE_DEG

    def residuals(params):
        knee, hip = forward(params)
        res = []
        if fix_depth:
            # y grows downward: hip below knee means hip.y - knee.y > 0. Weighted well above the
            # preference terms below: depth is the standard the target exists to satisfy, so it
            # must not be traded away a few thousandths at a time against staying near the
            # observed pose. Left unweighted it converged to 0.057 against its own 0.060 margin
            # and the target quietly failed the rule it was drawn to demonstrate.
            res.append(8.0 * ((hip[1] - knee[1]) - target_hip_below) / shin)
        else:
            res.append(((hip[1] - knee[1]) - (P["hip"][1] - P["knee"][1])) / shin)

        # Ankle range, one-sided: never ask for more shin lean than this athlete demonstrated.
        # Depth has to come from the hips travelling back instead, which is what the document
        # prescribes anyway: "sit back, lean forward, and shove your knees out" (ref p.33).
        lean = abs(np.degrees(np.arctan2(abs(knee[0] - ankle[0]), abs(knee[1] - ankle[1]))))
        res.append(3.0 * max(0.0, lean - shin_lean_limit) / 10.0)

        # Do not fix one criterion by breaking another. A one-sided penalty keeps the knee
        # inside its own tolerance without pulling it back when it is already fine.
        knee_past_toe = (knee[0] - toe_x) * facing / shin
        res.append(2.0 * max(0.0, knee_past_toe - knee_forward_limit))

        # Balance, also one-sided: sitting back is the mechanism, sitting down is the failure.
        hip_behind = (hip[0] - midfoot_x) * -facing / shin
        res.append(3.0 * max(0.0, hip_behind - BALANCE_LIMIT_SHIN))

        # Stay near the observed pose so the correction is the smallest one that works.
        res.append(0.25 * (params[0] - theta0))
        res.append(0.25 * (params[1] - phi0))
        return res

    sol = least_squares(residuals, x0=[theta0, phi0], max_nfev=400)
    knee_t, hip_t = forward(sol.x)

    # Did the ankle limit stop us reaching depth? If so the honest answer is not a ghost standing
    # somewhere the athlete cannot get to - it is that depth needs ankle mobility or a change of
    # stance, not a cue. The document itself treats an athlete who cannot reach depth as a
    # mobility problem rather than an effort problem (ref p.33).
    depth_shortfall = 0.0
    depth_progress = 1.0
    if fix_depth:
        got = (P["hip"][1] - P["knee"][1]) / shin
        want = target_hip_below / shin
        reached = (hip_t[1] - knee_t[1]) / shin
        depth_shortfall = want - reached
        if want - got > 1e-6:
            depth_progress = (reached - got) / (want - got)

    target_lean = abs(np.degrees(np.arctan2(
        abs(knee_t[0] - ankle[0]), abs(knee_t[1] - ankle[1]),
    )))
    hip_behind = (hip_t[0] - midfoot_x) * -facing / shin

    # Which limit actually bound, so the message can name it. Depth is usually reachable by
    # rotating the femur, so when it is not, saying "ankle" would often be simply wrong.
    # bool() on every comparison: these operands are numpy scalars, so `<` yields np.bool_, and
    # numpy 2 reports that type's name as plain "bool" - which makes the resulting
    # "Object of type bool is not JSON serializable" look self-contradictory when it surfaces
    # three layers away in the API response.
    depth_limited = bool(fix_depth and depth_progress < MIN_DEPTH_PROGRESS)
    limit_reason = None
    if depth_limited:
        at_ankle = bool(target_lean >= shin_lean_limit - 0.5)
        at_balance = bool(hip_behind >= BALANCE_LIMIT_SHIN - 0.02)
        if at_ankle and at_balance:
            limit_reason = "ankle_and_balance"
        elif at_balance:
            limit_reason = "balance"
        elif at_ankle:
            limit_reason = "ankle"
        else:
            limit_reason = "unknown"

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
        opening = (
            f"At the bottom your hip was {abs(got):.2f} shin-lengths {where} your knee - "
            f"close enough to level that we could not call it either way. The standard wants it "
            f"{want:.2f} below the knee, clearly past parallel. "
        )
        if depth_limited:
            because = {
                "ankle": (
                    f"Your shin already leans {observed_shin_lean:.0f} degrees at the bottom, and "
                    f"keeping the heel down limits how much further it can go. Forcing past that "
                    f"lifts the heel, and the document requires the feet flat (ref p.23)."
                ),
                "balance": (
                    "The hips would have to travel further back than you could stay balanced "
                    "over, which means sitting down rather than sitting back."
                ),
                "ankle_and_balance": (
                    f"Your shin already leans {observed_shin_lean:.0f} degrees with the heel down, "
                    f"and the hips would have to travel further back than you could stay balanced "
                    f"over. Both routes to the extra depth are closed from this stance."
                ),
            }.get(limit_reason, "We could not identify which limit stopped the solve, so treat "
                                "this target as indicative only.")
            corrections.append({
                "criterion_id": "depth",
                "label": "Depth needs mobility work, not a cue",
                "detail": (
                    opening +
                    f"We could not place a target you could actually reach. Your foot stays "
                    f"planted and your bones do not change length, so the only ways down are the "
                    f"hips travelling back or the shin leaning further forward. " + because +
                    f" That leaves about {depth_shortfall:.2f} shin-lengths of depth out of reach "
                    f"from this stance: something to work on with ankle range and foot position, "
                    f"not to force on the next repetition."
                ),
                "provenance": "document_stated rule, engineering_tolerance margin and limits",
            })
        else:
            corrections.append({
                "criterion_id": "depth",
                "label": "Sit back and down",
                "detail": (
                    opening +
                    f"The ghost shows where it needed to be. Because your foot stays planted and "
                    f"your bones do not change length, reaching it means the hip travels about "
                    f"{abs(hip_t[1] - P['hip'][1]) / shin:.2f} shin-lengths further down and "
                    f"further back, with the shin held near the "
                    f"{observed_shin_lean:.0f} degrees of lean you already showed rather than "
                    f"driving the knees forward. Depth comes from the hips going back."
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
        note=(
            "The target pose solver did not fully converge." if not sol.success
            else "This is the deepest position actually reachable from this stance, which is "
                 "short of the depth standard. Read it as where your current range stops you, "
                 "not as a position to force." if depth_limited
            else None
        ),
        depth_limited=depth_limited,
        limit_reason=limit_reason,
        # float() before round(): numpy scalars survive round() as np.float64, which json
        # refuses, and the failure lands in the API response rather than here.
        observed_shin_lean_deg=round(float(observed_shin_lean), 1),
        target_shin_lean_deg=round(float(target_lean), 1),
        hip_behind_midfoot_shin=round(float(hip_behind), 3),
    )
