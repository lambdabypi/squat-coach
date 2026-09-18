"""Fetch a test clip from a URL, transcoded to something both the browser and OpenCV can read.

Test footage is the scarcest thing in this project: every verdict so far came from one squat. A
new clip is worth more than any amount of re-reading the code.

Two constraints that are easy to get wrong:
  * The browser-pose path decodes frames from a <video> element, so the file has to be H.264 in
    MP4. A VP9 or AV1 download plays fine in Chrome and then yields nothing useful to seek-based
    frame extraction on some machines, which would look like a bug in the pose code.
  * Squat clips on video platforms are usually embedded in a longer talking-head edit. --start
    and --duration trim to the movement, because the rep segmenter looks for hip-height minima
    and a minute of someone explaining the squat is just noise in front of them.

    python scripts/fetch_test_clip.py URL --out samples/clip.mp4 [--start 14 --duration 12]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yt_dlp

# Prefer H.264 in MP4 at a sane height. Anything taller is wasted: the browser path downscales
# to 720 wide before running pose, and the server path is CPU-bound on frame count and area.
FORMAT = (
    "bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/"
    "best[ext=mp4][vcodec^=avc1][height<=1080]/"
    "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
)


def probe(path: Path) -> dict:
    fields = "stream=width,height,r_frame_rate,nb_frames,codec_name,duration"
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", fields, "-of", "default=nw=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=None, help="trim start, seconds")
    ap.add_argument("--duration", type=float, default=None, help="trim length, seconds")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + "_raw.mp4")

    opts = {
        "format": FORMAT,
        "outtmpl": str(raw),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(args.url, download=True)

    print(f"title    : {info.get('title')}")
    print(f"uploader : {info.get('uploader')}")
    print(f"duration : {info.get('duration')}s")

    if not raw.exists():
        print(f"download produced no file at {raw}", file=sys.stderr)
        return 1

    # Always re-encode rather than stream-copy. A stream copy trimmed to --start begins at the
    # nearest keyframe, so the requested second and the actual first frame can differ by a second
    # or more, and any leading non-H.264 stream would survive untouched.
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if args.start is not None:
        cmd += ["-ss", str(args.start)]
    cmd += ["-i", str(raw)]
    if args.duration is not None:
        cmd += ["-t", str(args.duration)]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-crf", "20", "-an", str(out)]
    subprocess.run(cmd, check=True)
    raw.unlink(missing_ok=True)

    p = probe(out)
    print(f"\nwrote {out}")
    print(f"  {p.get('width')}x{p.get('height')}  {p.get('codec_name')}  "
          f"{p.get('r_frame_rate')} fps  {p.get('nb_frames')} frames  {p.get('duration')}s")
    if p.get("codec_name") != "h264":
        print(f"  WARNING: codec is {p.get('codec_name')}, not h264; the browser-pose path may "
              f"not be able to seek frames from it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
