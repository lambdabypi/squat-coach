"""Does the analysis survive a video that is not the one clip it was built on?

Every verdict this project has ever produced came from a single squat clip. That is the honest
limit on any accuracy claim, and it cannot be fixed without more footage. What it CAN do is stress
the pipeline along the axes a different upload would actually differ on, by transforming the one
clip available:

  mirrored  - athlete faces the other way. Exercises near-side selection and every `facing` sign
              in the metrics and the target-pose solver. Sign errors are a classic failure and
              they are invisible on a clip where the athlete only ever faces one way.
  half_res  - 540x960 instead of 1080x1920. The bar detector searches an absolute pixel radius
              range and the scale estimate assumes a 450mm plate, so resolution is load-bearing.
  fps15     - half the frame rate. Exercises the Savitzky-Golay window and rep segmentation.
  dark      - underexposed. Exercises landmark confidence and Hough sensitivity.

A verdict SHOULD be allowed to move if the underlying measurement genuinely changed, but the
mirrored clip is a special case: it is the same squat, so any verdict difference there is a bug in
this code, not a property of the video. That makes it the strongest single test available here.

    python scripts/check_generalisation.py <baseline.mp4> <variant.mp4> [<variant.mp4> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import analyse  # noqa: E402

# Mirroring is not a change to the movement, so these must match the baseline exactly. Anything
# else is a sign convention that only worked because the athlete faced one particular way.
MIRROR_INVARIANT = "mirrored"


def collect(video: Path) -> dict:
    out = analyse(video, use_agent=False)
    report = out["report"]

    # Verdicts live in report["findings"], flat, one row per (rep, criterion). An earlier version
    # of this script read report["repetitions"], which does not exist: every dict was empty, the
    # comparison ran over zero verdicts, and it printed a confident pass. Assert instead, so a
    # renamed key fails loudly rather than silently testing nothing.
    findings = report.get("findings")
    if not findings:
        raise KeyError("report has no 'findings'; this script would otherwise compare nothing")

    verdicts: dict[str, str] = {}
    values: dict[str, float | None] = {}
    for a in findings:
        key = f"rep{a['rep_index']}.{a['criterion_id']}"
        verdicts[key] = a["verdict"]
        m = a.get("measurement") or {}
        values[key] = m.get("value") if isinstance(m, dict) else None

    targets = out["overlay"].get("target_poses") or {}
    return {
        "reps": len(report.get("reps", [])),
        "verdicts": verdicts,
        "values": values,
        "shin": report["pose"]["shin_length_px"],
        "scale": report.get("scale", {}).get("mm_per_px"),
        "targets": {
            k: {
                "observed_lean": t.get("observed_shin_lean_deg"),
                "target_lean": t.get("target_shin_lean_deg"),
                "depth_limited": t.get("depth_limited"),
                "limit_reason": t.get("limit_reason"),
            }
            for k, t in targets.items()
        },
    }


def main() -> int:
    base_path = Path(sys.argv[1])
    print(f"baseline: {base_path.name}")
    base = collect(base_path)
    print(f"  reps={base['reps']}  shin={base['shin']:.1f}px  "
          f"scale={base['scale'] if base['scale'] else 'unavailable'}")
    for k, t in sorted(base["targets"].items()):
        print(f"  target rep{k}: lean {t['observed_lean']} -> {t['target_lean']} deg, "
              f"depth_limited={t['depth_limited']}")

    problems = 0
    for arg in sys.argv[2:]:
        path = Path(arg)
        name = path.stem
        print(f"\n=== {name} ===")
        try:
            var = collect(path)
        except Exception as exc:  # a crash is the worst outcome and must be reported as one
            print(f"  CRASHED: {type(exc).__name__}: {exc}")
            problems += 1
            continue

        print(f"  reps={var['reps']} (baseline {base['reps']})  "
              f"shin={var['shin']:.1f}px  "
              f"scale={var['scale'] if var['scale'] else 'unavailable'}")
        if var["reps"] != base["reps"]:
            print(f"  DIFFERENT REP COUNT: {base['reps']} -> {var['reps']}")
            problems += 1

        moved = [k for k in sorted(set(base["verdicts"]) | set(var["verdicts"]))
                 if base["verdicts"].get(k) != var["verdicts"].get(k)]
        print(f"  verdicts changed: {len(moved)} of "
              f"{len(set(base['verdicts']) | set(var['verdicts']))}")
        for k in moved:
            bv, vv = base["verdicts"].get(k, "absent"), var["verdicts"].get(k, "absent")
            b_val, v_val = base["values"].get(k), var["values"].get(k)
            fmt = lambda v: "none" if v is None else f"{v:+.3f}"
            print(f"    {k:34s} {bv} -> {vv}   ({fmt(b_val)} -> {fmt(v_val)})")

        for k, t in sorted(var["targets"].items()):
            bt = base["targets"].get(k, {})
            print(f"  target rep{k}: lean {t['observed_lean']} -> {t['target_lean']} deg, "
                  f"depth_limited={t['depth_limited']}"
                  + (f" ({t['limit_reason']})" if t["depth_limited"] else "")
                  + (f"   [baseline target_lean {bt.get('target_lean')}]" if bt else ""))
            # The target must never ask for ankle range the athlete did not show, on any input.
            if t["observed_lean"] is not None and t["target_lean"] is not None:
                extra = t["target_lean"] - t["observed_lean"]
                if extra > 5.0:
                    print(f"    TARGET DEMANDS {extra:.1f} deg MORE ankle range than observed")
                    problems += 1

        if name == MIRROR_INVARIANT and moved:
            print("  MIRROR TEST FAILED: the same squat filmed the other way produced different")
            print("  verdicts, which is a sign-convention bug in this code, not a video property")
            problems += 1

    print("\n" + "=" * 72)
    if problems:
        print(f"{problems} problem(s) found across the variants.")
        return 1
    print("No crashes, no rep-count changes, no target asking for unobserved ankle range, and")
    print("the mirrored clip reproduced the baseline verdicts exactly.")
    print("This is still one underlying squat. It does not establish accuracy on a new athlete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
