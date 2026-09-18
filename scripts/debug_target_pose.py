"""Why is the target pose missing from the report?

The UI shows a "Target pose" toggle whenever any repetition has one, but renders the "What to
change" panel only for the repetition on screen. If one rep has a correction and another does
not, the toggle appears with nothing behind it. This prints what each rep actually produced, so
the answer comes from the data rather than from reading the JSX again.

    python scripts/debug_target_pose.py <video>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import analyse  # noqa: E402

CORRECTABLE = {"depth", "back_angle"}


def main() -> int:
    video = Path(sys.argv[1])
    out = analyse(video, use_agent=False)
    report, overlay = out["report"], out["overlay"]

    print(f"reps: {[r['index'] for r in report['reps']]}")
    print(f"target_poses keys: {sorted((overlay.get('target_poses') or {}).keys())}\n")

    for rep in report["reps"]:
        i = rep["index"]
        print(f"--- rep {i} ---")
        for f in report["findings"]:
            if f["rep_index"] != i or f["criterion_id"] not in CORRECTABLE:
                continue
            m = f.get("measurement")
            avail = bool(m and m.get("available"))
            # This is the condition the pipeline uses to decide a criterion is correctable.
            eligible = f["verdict"] in ("does_not_meet_standard", "cannot_assess") and avail
            print(f"  {f['criterion_id']:12s} {f['verdict']:24s} "
                  f"measured={avail}  -> correctable={eligible}")

        tp = (overlay.get("target_poses") or {}).get(str(i))
        if tp is None:
            print("  NO TARGET POSE for this rep -> the panel cannot render")
        else:
            print(f"  target pose: solved={tp['solved']}, "
                  f"{len(tp['corrections'])} correction(s)")
            for c in tp["corrections"]:
                print(f"    - {c['label']}")
            if not tp["corrections"]:
                print("  target pose exists but has NO corrections -> the panel is hidden")
        print()

    keys = set((overlay.get("target_poses") or {}).keys())
    reps = {str(r["index"]) for r in report["reps"]}
    missing = sorted(reps - keys)
    if missing:
        print(f"Reps with no target pose: {missing}")
        print("The toggle shows because ANOTHER rep has one. Selecting a rep without a")
        print("correction leaves the toggle visible and the panel absent, which is the")
        print("inconsistency to fix in the UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
