"""Export annotated still frames at each repetition's bottom position.

Draws from the same overlay.json the browser uses, so what lands on disk is exactly what the UI
renders — which makes these stills usable as evidence rather than a separate rendering path that
might disagree with the product.

    python scripts/export_frames.py <video> <out_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

GREEN = (80, 185, 63)      # landmark actually seen
ORANGE = (62, 136, 240)    # landmark inferred by the model
BLUE = (255, 166, 88)
BAR = (102, 209, 255)
GREY = (158, 148, 139)
GHOST = (196, 242, 94)     # corrected pose, BGR


def main() -> int:
    video = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    overlay = json.loads((out_dir / "overlay.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"could not open {video}")
        return 1

    wanted = {}
    for rep in overlay["reps"]:
        wanted[rep["bottom_frame"]] = f"rep{rep['index']}_bottom"
        wanted[rep["start_frame"]] = f"rep{rep['index']}_top"

    written = 0
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in wanted:
            f = overlay["frames"][idx] if idx < len(overlay["frames"]) else None
            if f:
                # bar path travelled so far
                pts = [p for p in overlay["bar_path"]
                       if p["x"] is not None and p["t"] <= f["t"]]
                for a, b in zip(pts, pts[1:]):
                    cv2.line(frame, (int(a["x"]), int(a["y"])),
                             (int(b["x"]), int(b["y"])), BAR, 3)

                for ja, jb in overlay["skeleton"]:
                    pa, pb = f["joints"].get(ja), f["joints"].get(jb)
                    if not pa or not pb or pa["x"] is None or pb["x"] is None:
                        continue
                    cv2.line(frame, (int(pa["x"]), int(pa["y"])),
                             (int(pb["x"]), int(pb["y"])), BLUE, 4)

                for name, j in f["joints"].items():
                    if j["x"] is None or name in ("nose", "ear"):
                        continue
                    cv2.circle(frame, (int(j["x"]), int(j["y"])), 9,
                               GREEN if j["visible"] else ORANGE, -1)

                if f["bar"]["x"] is not None:
                    cv2.circle(frame, (int(f["bar"]["x"]), int(f["bar"]["y"])), 14,
                               BAR if f["bar"]["observed"] else GREY, -1)

                # Corrected-pose ghost, if one was solved for this frame.
                for tp in (overlay.get("target_poses") or {}).values():
                    if abs(tp["frame"] - idx) > 1:
                        continue
                    chain = [tp["ankle"], tp["knee"], tp["hip"], tp["shoulder"]]
                    pts = [(int(p[0]), int(p[1])) for p in chain]
                    for a, b in zip(pts, pts[1:]):
                        cv2.line(frame, a, b, GHOST, 5, cv2.LINE_AA)
                    for p in pts:
                        cv2.circle(frame, p, 10, GHOST, -1)
                    hip_actual = f["joints"]["hip"]
                    if hip_actual["x"] is not None:
                        cv2.arrowedLine(
                            frame,
                            (int(hip_actual["x"]), int(hip_actual["y"])),
                            pts[2], GHOST, 4, cv2.LINE_AA, tipLength=0.25,
                        )
                    cv2.putText(frame, "TARGET", (pts[2][0] + 16, pts[2][1] + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
                    cv2.putText(frame, "TARGET", (pts[2][0] + 16, pts[2][1] + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, GHOST, 2)

                label = f"{wanted[idx]}  t={f['t']:.2f}s  frame={idx}"
                cv2.putText(frame, label, (16, 42), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (0, 0, 0), 5)
                cv2.putText(frame, label, (16, 42), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (255, 255, 255), 2)

            path = out_dir / f"{wanted[idx]}.jpg"
            cv2.imwrite(str(path), frame)
            written += 1
            print(f"wrote {path.name}")
        idx += 1
    cap.release()
    print(f"{written} frames written; {len(report['findings'])} findings in the report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
