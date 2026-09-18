"""Headless pipeline: video -> evidence + findings JSON.

This is the debugging and evidence-gathering path, and it exercises exactly the same code the
API does. Use --no-agent to run the deterministic layer only (no API key needed, no cost).

    python scripts/run_cli.py <video> [--out DIR] [--no-agent]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.pipeline import analyse  # noqa: E402

VERDICT_MARK = {
    "meets_standard": "PASS",
    "does_not_meet_standard": "FAIL",
    "cannot_assess": "----",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-agent", action="store_true")
    args = ap.parse_args()

    video = Path(args.video)
    out_dir = Path(args.out) if args.out else video.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    result = analyse(
        video,
        use_agent=not args.no_agent,
        progress=lambda stage, pct: print(f"  [{pct:5.1%}] {stage}", flush=True),
    )
    elapsed = time.perf_counter() - t0

    report = result["report"]
    print(f"\n{'=' * 78}")
    print(f"{video.name} - analysed in {elapsed:.1f}s")
    print(f"{'=' * 78}")

    info = report["video"]
    print(f"video   : {info['width']}x{info['height']} {info['fps']:.1f}fps {info['duration_s']:.2f}s")
    print(f"side    : {report['pose']['side']} facing camera")
    print(f"reps    : {len(report['reps'])}")

    print("\nquality gates:")
    for g in report["quality"]["gates"]:
        mark = "ok  " if g["passed"] and g["severity"] == "ok" else \
               "warn" if g["passed"] else "FAIL"
        print(f"  [{mark}] {g['id']:18s} {g['detail'][:96]}")

    if report.get("summary"):
        print(f"\nsummary:\n  {report['summary']}")

    print("\nfindings:")
    for rep in report["reps"]:
        print(f"\n  --- repetition {rep['index']}  "
              f"(bottom at {rep['bottom_t']:.2f}s, confidence {rep['confidence']}) ---")
        for f in report["findings"]:
            if f["rep_index"] != rep["index"]:
                continue
            m = f.get("measurement")
            val = ""
            if m and m.get("value") is not None:
                val = f"{m['value']:+.3f} {m['unit']}"
                if m.get("basis") == "estimated":
                    val += " (estimated)"
            print(f"    {VERDICT_MARK[f['verdict']]}  {f['criterion_name']:32s} "
                  f"{val:28s} [{f['confidence']}] {f['citation']}")
            print(f"          {f['explanation'][:150]}")
            if f.get("uncertainty"):
                print(f"          uncertainty: {f['uncertainty'][:130]}")

    counts: dict[str, int] = {}
    for f in report["findings"]:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
    print(f"\nverdict counts: {counts}")
    if report.get("cost"):
        print(f"cost: {json.dumps(report['cost'])}")

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    overlay_path = out_dir / "overlay.json"
    overlay_path.write_text(json.dumps(result["overlay"], indent=2), encoding="utf-8")
    print(f"\nwrote {report_path}")
    print(f"wrote {overlay_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
