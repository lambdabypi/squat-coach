"""Download the MediaPipe pose landmarker model (not committed; ~31 MB)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
       "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task")
DEST = Path(__file__).resolve().parents[1] / "backend" / "models" / "pose_landmarker_heavy.task"


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        print(f"already present: {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
        return 0
    print(f"downloading {URL}")
    urllib.request.urlretrieve(URL, DEST)
    print(f"wrote {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
