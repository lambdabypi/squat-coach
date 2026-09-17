"""Download the assignment's common sample video.

Note: yt-dlp is deliberately NOT pinned in requirements.txt. A pinned copy broke on YouTube's
signature extraction during this build and had to be upgraded mid-run; a downloader that tracks
a moving target should float.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

URL = "https://youtube.com/shorts/TRvg083BrXY"
DEST_DIR = Path(__file__).resolve().parents[1] / "EVIDENCE" / "common-sample"


def main() -> int:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    out = DEST_DIR / "common_sample.%(ext)s"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "-o", str(out), URL,
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\nDownload failed. If this is a YouTube signature error, upgrade the downloader:")
        print(f"  {sys.executable} -m pip install --upgrade yt-dlp")
        return result.returncode
    print(f"saved to {DEST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
