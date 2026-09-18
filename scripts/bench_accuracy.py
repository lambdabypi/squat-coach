"""Does the faster pose model change the answers?

bench_speed.py shows a 13x speed-up from a lighter model at half resolution. That is only a
real option if the measurements and verdicts survive it. Speed without agreement is not a
speed-up, it is a different product.

Runs the full pipeline under each pose model and compares the numbers that reach the user.

    python scripts/bench_accuracy.py <video>
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

VARIANTS = ["heavy", "full", "lite"]


def run(video: Path, variant: str) -> dict:
    os.environ["POSE_MODEL"] = variant
    # The variant is read at import time, so the vision modules have to be reloaded.
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]
    pipeline = importlib.import_module("app.pipeline")

    t0 = time.perf_counter()
    result = pipeline.analyse(video, use_agent=False)
    elapsed = time.perf_counter() - t0

    report = result["report"]
    out = {
        "variant": variant,
        "seconds": round(elapsed, 1),
        "reps": len(report["reps"]),
        "shin_px": report["pose"]["shin_length_px"],
        "bar_pct": round(report["bar"]["observed_fraction"] * 100),
        "verdicts": {},
        "measures": {},
    }
    for f in report["findings"]:
        key = (f["rep_index"], f["criterion_id"])
        out["verdicts"][key] = f["verdict"]
        m = f.get("measurement")
        if m and m.get("value") is not None:
            out["measures"][key] = m["value"]
    return out


def main() -> int:
    video = Path(sys.argv[1])
    runs = {}
    for v in VARIANTS:
        print(f"running {v}...", flush=True)
        runs[v] = run(video, v)

    base = runs["heavy"]
    print(f"\n{'variant':8s} {'sec':>6s} {'speedup':>8s} {'reps':>5s} {'shin px':>8s} {'bar%':>5s}")
    print("-" * 48)
    for v in VARIANTS:
        r = runs[v]
        print(f"{v:8s} {r['seconds']:6.1f} {base['seconds'] / r['seconds']:7.1f}x "
              f"{r['reps']:5d} {r['shin_px']:8.1f} {r['bar_pct']:4d}%")

    for v in VARIANTS[1:]:
        r = runs[v]
        print(f"\n=== {v} vs heavy ===")

        flips = [
            (k, base["verdicts"][k], r["verdicts"].get(k))
            for k in base["verdicts"]
            if r["verdicts"].get(k) != base["verdicts"][k]
        ]
        if flips:
            print(f"  {len(flips)} VERDICT CHANGE(S):")
            for (rep, cid), a, b in flips:
                print(f"    rep{rep} {cid:26s} {a} -> {b}")
        else:
            print("  no verdict changes")

        deltas = []
        for k, v0 in base["measures"].items():
            v1 = r["measures"].get(k)
            if v1 is None:
                continue
            deltas.append((abs(v1 - v0), k, v0, v1))
        deltas.sort(reverse=True)
        if deltas:
            print("  largest measurement differences:")
            for d, (rep, cid), v0, v1 in deltas[:5]:
                print(f"    rep{rep} {cid:26s} {v0:+8.3f} -> {v1:+8.3f}  (delta {d:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
