"""Is the solved target position something a human could actually hold?

scripts/test_target_pose.py checks that the target is GEOMETRICALLY valid: bone lengths
preserved, foot planted, depth achieved, other criteria not broken. That is a different question
from whether a body can get there.

A deeper squat with a planted foot can be reached two ways: the hips travel back, or the knee
goes forward and the shin inclines further. The second needs dorsiflexion the athlete may not
have, and past that limit the heel lifts, which breaks the document's own "feet flat on the
ground" requirement (ref p.23).

An earlier solver had no ankle model at all and took the second route, asking for 55 degrees of
shin lean against the 39 the athlete showed. It now holds the shin to the lean the athlete
demonstrated, plus a small allowance, and reports depth it cannot reach that way as an ankle
limit. This script is what measures whether that holds:
  - shin inclination, observed against target, and the extra dorsiflexion implied
  - knee travel past the toe
  - whether a target short of depth is honestly marked ankle-limited

The primary test is the athlete against themselves: they held the observed lean on video with
the heel down, so that angle is evidence of their range. Population dorsiflexion figures (about
20-30 degrees unshod, more in raised-heel shoes) are printed as context only, because on real
clips the observed lean can exceed them - which says the population range does not describe this
athlete, not that their own position was impossible.

    python scripts/check_target_feasible.py <video>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import analyse  # noqa: E402
from app.vision.target_pose import ANKLE_ALLOWANCE_DEG, TARGET_DEPTH_MARGIN_SHIN  # noqa: E402

DEPTH_MARGIN_SHIN = TARGET_DEPTH_MARGIN_SHIN

# How far behind the midfoot the target hip may sit, in shin-lengths. The hip is behind the foot
# in every real squat - that is what sitting back means - so this is a generous outer limit meant
# to catch a solver that buys depth by tipping the athlete over, not a posture prescription.
BALANCE_LIMIT_SHIN = 0.60

# Population reference points, reported as context only. They are not measurements of this
# athlete, and the athlete's own demonstrated lean is what the solver is actually held to.
TYPICAL_DORSIFLEXION_DEG = 25.0
SHOD_DORSIFLEXION_DEG = 35.0


def shin_angle_from_vertical(ankle, knee) -> float:
    """Degrees the shin leans away from vertical. Larger means more dorsiflexion required."""
    v = np.array(knee, float) - np.array(ankle, float)
    return float(np.degrees(np.arctan2(abs(v[0]), abs(v[1]))))


def main() -> int:
    video = Path(sys.argv[1])
    out = analyse(video, use_agent=False)
    report, overlay = out["report"], out["overlay"]
    shin = report["pose"]["shin_length_px"]
    targets = overlay.get("target_poses") or {}

    if not targets:
        print("No target positions were solved for this clip.")
        return 0

    concerns = 0
    for key, tp in sorted(targets.items(), key=lambda kv: int(kv[0])):
        if not tp["corrections"]:
            continue
        f = overlay["frames"][tp["frame"]]
        j = f["joints"]
        if j["ankle"]["x"] is None or j["knee"]["x"] is None:
            continue

        a_obs = (j["ankle"]["x"], j["ankle"]["y"])
        k_obs = (j["knee"]["x"], j["knee"]["y"])
        a_tgt, k_tgt = tuple(tp["ankle"]), tuple(tp["knee"])

        obs = shin_angle_from_vertical(a_obs, k_obs)
        tgt = shin_angle_from_vertical(a_tgt, k_tgt)
        extra = tgt - obs

        print(f"=== repetition {key} (frame {tp['frame']}) ===")
        print(f"  shin lean from vertical : {obs:5.1f} deg observed "
              f"-> {tgt:5.1f} deg target   ({extra:+.1f} deg)")

        # Knee travel past the toe, in the direction the athlete faces.
        toe = (j["toe"]["x"], j["toe"]["y"])
        heel = (j["heel"]["x"], j["heel"]["y"])
        facing = np.sign(toe[0] - heel[0]) or 1.0
        k_past_obs = (k_obs[0] - toe[0]) * facing / shin
        k_past_tgt = (k_tgt[0] - toe[0]) * facing / shin
        print(f"  knee past the toe       : {k_past_obs:+.3f} -> {k_past_tgt:+.3f} shin-lengths")

        # Depth actually delivered.
        d_obs = (j["hip"]["y"] - j["knee"]["y"]) / shin
        d_tgt = (tp["hip"][1] - tp["knee"][1]) / shin
        print(f"  hip relative to knee    : {d_obs:+.3f} -> {d_tgt:+.3f} shin-lengths")

        # Balance. Depth now comes from the hips travelling back, so the failure mode to watch
        # has inverted: not a knee driven past its limit, but a hip so far behind the foot that
        # the athlete would sit down. Measured behind the midfoot, in the facing direction.
        midfoot_x = (toe[0] + heel[0]) / 2.0
        b_obs = (j["hip"]["x"] - midfoot_x) * -facing / shin
        b_tgt = (tp["hip"][0] - midfoot_x) * -facing / shin
        print(f"  hip behind the midfoot  : {b_obs:+.3f} -> {b_tgt:+.3f} shin-lengths")
        if b_tgt > BALANCE_LIMIT_SHIN:
            print(f"    hip sits {b_tgt:.2f} shin-lengths behind the midfoot, past the "
                  f"{BALANCE_LIMIT_SHIN:.2f} balance limit:")
            print("    this target trades depth for a position the athlete would fall out of")
            concerns += 1

        limited = bool(tp.get("depth_limited"))
        print(f"  depth-limited           : {'yes' if limited else 'no'}"
              + (f" ({tp.get('limit_reason')})" if limited else ""))

        # The primary test is the athlete against themselves. They held the observed lean on
        # video with the heel down, so that angle is evidence of their range in a way no
        # population average is. Anything beyond it is a demand we cannot support.
        print("  feasibility:")
        if extra <= ANKLE_ALLOWANCE_DEG + 0.5:
            print(f"    target shin lean is within the {ANKLE_ALLOWANCE_DEG:.0f} deg allowance over")
            print(f"    what this athlete already demonstrated, so it asks for no ankle range")
            print("    they have not shown with the heel down")
        else:
            print(f"    demands {extra:.0f} deg MORE dorsiflexion than the athlete showed here,")
            print("    which is a mobility change, not a cue they can just apply")
            concerns += 1

        # 0.002 shin-lengths is well under a pixel of hip position on this footage: a solver
        # converging to within that has met the margin, and a tighter epsilon just reports
        # floating point back at us.
        if d_tgt + 0.002 < DEPTH_MARGIN_SHIN and not limited:
            print(f"    target depth {d_tgt:+.3f} is short of the {DEPTH_MARGIN_SHIN:.2f} standard")
            print("    but the pose was not marked depth-limited, so the shortfall is unexplained")
            concerns += 1
        if limited and tp.get("limit_reason") == "unknown":
            print("    marked depth-limited but neither the ankle nor the balance limit was")
            print("    binding, so the reported reason would be a guess")
            concerns += 1

        # Population figures, reported as context only. On this clip the observed lean already
        # exceeds them, which says the population range is the wrong yardstick for this athlete
        # (or that 2D projection inflates the angle) - not that their own position is impossible.
        if obs > SHOD_DORSIFLEXION_DEG:
            print(f"    context: the OBSERVED lean of {obs:.0f} deg already exceeds the population")
            print(f"    shod reference of {SHOD_DORSIFLEXION_DEG:.0f} deg, so that reference does not")
            print("    describe this athlete, or the 2D view inflates the angle. Either way the")
            print("    athlete's own demonstrated lean is the more defensible limit.")
        print()

    print("=" * 72)
    if concerns:
        print(f"{concerns} feasibility concern(s): the target asks for ankle range this athlete")
        print("has not demonstrated, or falls short of depth without saying why.")
        return 1
    print("No feasibility concerns on this clip. Every target stays within the ankle range the")
    print("athlete demonstrated with the heel down, and any depth it cannot reach is reported")
    print("as an ankle limit rather than drawn as a position to force.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
