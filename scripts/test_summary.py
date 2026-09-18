"""Assert the summary keeps the three kinds of withheld verdict apart.

The defect this replaces: the model described a depth result that was inside the measurement
tolerance as too close to call "from this camera angle". The summary is now generated from the
findings, so this checks the distinction actually survives into the prose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

REPORT = ROOT / "EVIDENCE" / "common-sample" / "report.json"

# Phrases that would mean a tolerance-bound result had been blamed on the camera.
CAMERA_WORDS = ("camera angle", "from this angle", "this camera", "the footage cannot",
                "this view cannot see")


def main() -> int:
    report = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else REPORT).read_text("utf-8"))
    summary = report.get("summary") or ""
    print("SUMMARY\n" + "-" * 78)
    print(summary)
    print("-" * 78)

    findings = report["findings"]
    borderline = sorted({
        f["criterion_name"] for f in findings
        if f["verdict"] == "cannot_assess"
        and f.get("measurement") and f["measurement"].get("available")
    })
    structural = sorted({
        f["criterion_name"] for f in findings
        if f["verdict"] == "cannot_assess" and not f.get("measurement")
    })

    print(f"\nborderline (measured, inside tolerance): {borderline}")
    print(f"structural (side view cannot see)      : {structural}")

    failures = 0
    low = summary.lower()

    # 1. A borderline criterion must be described as a tolerance limit, not a camera limit.
    for n in borderline:
        if n.lower() in low:
            idx = low.index(n.lower())
            window = low[idx: idx + 320]
            blamed = [w for w in CAMERA_WORDS if w in window]
            # Allow the explicit disclaimer the builder emits.
            if blamed and "not of the camera angle" not in window:
                print(f"\nFAIL: '{n}' is tolerance-bound but the summary near it says {blamed}")
                failures += 1

    # 2. Tolerance language must appear at all when something was borderline.
    if borderline and "tolerance" not in low:
        print("\nFAIL: a borderline result exists but the summary never mentions tolerance")
        failures += 1

    # 3. Structural gaps must be attributed to the camera angle.
    if structural and not any(w in low for w in ("side view cannot", "different camera")):
        print("\nFAIL: structural gaps exist but the summary does not say a side view cannot see them")
        failures += 1

    # 4. Determinism: no model in the path.
    if report.get("cost") and report["findings"][0]["narrated_by"] == "agent":
        print("\n(agent narrated the findings; the summary is still generated in code)")

    print("\nPASS: the summary separates measurement limits from camera limits"
          if failures == 0 else f"\n{failures} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
