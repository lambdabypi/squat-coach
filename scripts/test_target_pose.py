"""Check that the corrected pose is physically valid and does not break other criteria.

A "target" that violates the document, or that silently lengthens the athlete's femur, would be
worse than no target at all. This re-measures the solved pose against the same rules the
assessment uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.skill.loader import load_skill  # noqa: E402

OVERLAY = ROOT / "EVIDENCE" / "common-sample" / "overlay.json"


def seg(a, b) -> float:
    return float(np.linalg.norm(np.array(a) - np.array(b)))


def main() -> int:
    overlay = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else OVERLAY).read_text("utf-8"))
    skill = load_skill()
    shin = overlay["shin_length_px"]
    depth_tol = skill.by_id("depth").tolerance.value
    knee_limit = skill.by_id("knee_forward_of_toes").tolerance.value
    back_ref = skill.by_id("back_angle").rule.reference_value
    back_tol = skill.by_id("back_angle").tolerance.value

    poses = overlay.get("target_poses") or {}
    if not poses:
        print("no target poses in this overlay")
        return 1

    failures = 0
    for rep_idx, tp in poses.items():
        f = overlay["frames"][tp["frame"]]
        j = f["joints"]
        actual = {k: (j[k]["x"], j[k]["y"]) for k in ("ankle", "knee", "hip", "shoulder")}
        target = {k: tuple(tp[k]) for k in ("ankle", "knee", "hip", "shoulder")}

        print(f"\n=== repetition {rep_idx} (frame {tp['frame']}, solved={tp['solved']}) ===")

        # 1. Bones must not change length.
        for name, (a, b) in (("tibia", ("ankle", "knee")),
                             ("femur", ("knee", "hip")),
                             ("torso", ("hip", "shoulder"))):
            la, lt = seg(actual[a], actual[b]), seg(target[a], target[b])
            drift = abs(la - lt) / la * 100
            ok = drift < 1.0
            failures += not ok
            print(f"  [{'ok  ' if ok else 'FAIL'}] {name:6s} {la:7.1f}px -> {lt:7.1f}px "
                  f"({drift:.2f}% drift)")

        # 2. Foot stays planted.
        moved = seg(actual["ankle"], target["ankle"])
        ok = moved < 2.0
        failures += not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] ankle moved {moved:.2f}px (foot must stay planted)")

        # 3. The target must actually satisfy depth.
        d = (target["hip"][1] - target["knee"][1]) / shin
        ok = d > depth_tol
        failures += not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] depth: hip {d:+.3f} shin below knee "
              f"(needs > {depth_tol} to clear tolerance)")
        d_actual = (actual["hip"][1] - actual["knee"][1]) / shin
        print(f"         was {d_actual:+.3f} - this is the correction being shown")

        # 4. It must not break knee position, which was passing.
        toe = (j["toe"]["x"], j["toe"]["y"])
        heel = (j["heel"]["x"], j["heel"]["y"])
        facing = np.sign(toe[0] - heel[0]) or 1.0
        kt = (target["knee"][0] - toe[0]) * facing / shin
        ka = (actual["knee"][0] - toe[0]) * facing / shin
        ok = kt <= knee_limit
        failures += not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] knee past toe: {ka:+.3f} -> {kt:+.3f} shin "
              f"(limit {knee_limit})")

        # 5. Back angle should stay within the document's band.
        v = np.array(target["shoulder"]) - np.array(target["hip"])
        ang = float(np.degrees(np.arctan2(abs(v[1]), abs(v[0]))))
        ok = abs(ang - back_ref) <= back_tol
        failures += not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] back angle {ang:.1f}deg "
              f"(reference {back_ref} +/- {back_tol})")

    print(f"\n{'ALL CHECKS PASS' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
