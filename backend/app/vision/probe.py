"""ffprobe gate.

Runs before any compute is spent. Every rejection here produces a reason string that is
shown verbatim to the user, because "we could not analyse this" with no explanation is the
failure mode the brief calls out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

# Limits. These are engineering limits for the time box, not document requirements.
MAX_DURATION_S = 60.0
MIN_DURATION_S = 1.5
MIN_FPS = 15.0
MIN_SHORT_SIDE_PX = 360
SUPPORTED_CODECS = {"h264", "hevc", "vp9", "av1", "mpeg4"}
SUPPORTED_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


class ProbeError(RuntimeError):
    """Raised when a video cannot be analysed. The message is user-facing."""


@dataclass
class VideoInfo:
    path: str
    filename: str
    codec: str
    width: int           # display width, after rotation is applied
    height: int          # display height, after rotation is applied
    fps: float
    duration_s: float
    frame_count: int
    rotation_deg: int
    is_portrait: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _ffprobe_json(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise ProbeError("ffprobe was not found on PATH. Install ffmpeg to analyse video.")
    proc = subprocess.run(
        [exe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise ProbeError(f"This file could not be read as a video. ffprobe said: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout.lstrip("﻿"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ProbeError(f"Could not parse video metadata: {exc}")


def _rotation_of(stream: dict) -> int:
    """Rotation in degrees, from either the modern side_data or the legacy tag."""
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(side["rotation"]) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    if tag is not None:
        try:
            return int(tag) % 360
        except ValueError:
            pass
    return 0


def _parse_rate(value: str | None) -> float:
    if not value or "/" not in value:
        try:
            return float(value or 0.0)
        except ValueError:
            return 0.0
    num, _, den = value.partition("/")
    try:
        d = float(den)
        return float(num) / d if d else 0.0
    except ValueError:
        return 0.0


def probe(path: str | Path) -> VideoInfo:
    """Inspect a video and raise ProbeError with a user-facing reason if unusable."""
    path = Path(path)
    if not path.exists():
        raise ProbeError("The uploaded file is missing.")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ProbeError(f"{path.suffix or 'This file type'} is not supported. Use one of: {supported}.")

    data = _ffprobe_json(path)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise ProbeError("This file contains no video track.")
    v = streams[0]

    codec = (v.get("codec_name") or "unknown").lower()
    if codec not in SUPPORTED_CODECS:
        raise ProbeError(f"The video codec '{codec}' is not supported. Re-export as H.264 MP4.")

    rotation = _rotation_of(v)
    width, height = int(v.get("width", 0)), int(v.get("height", 0))
    if rotation in (90, 270):
        width, height = height, width
    if min(width, height) < MIN_SHORT_SIDE_PX:
        raise ProbeError(
            f"The video is {width}x{height}. The short side must be at least "
            f"{MIN_SHORT_SIDE_PX}px for landmarks to be reliable."
        )

    fps = _parse_rate(v.get("avg_frame_rate")) or _parse_rate(v.get("r_frame_rate"))
    if fps < MIN_FPS:
        raise ProbeError(
            f"The video is {fps:.1f} fps. At least {MIN_FPS:.0f} fps is needed to time the "
            "bottom of each repetition."
        )

    duration_s = float(data.get("format", {}).get("duration") or v.get("duration") or 0.0)
    if duration_s <= 0:
        raise ProbeError("The video duration could not be determined; the file may be truncated.")
    if duration_s > MAX_DURATION_S:
        raise ProbeError(
            f"The video is {duration_s:.0f}s. Please trim it to {MAX_DURATION_S:.0f}s or less - "
            "a few repetitions is enough."
        )
    if duration_s < MIN_DURATION_S:
        raise ProbeError(f"The video is only {duration_s:.1f}s, too short to contain a repetition.")

    frame_count = int(v.get("nb_frames") or 0) or int(round(duration_s * fps))

    return VideoInfo(
        path=str(path),
        # Carried so the report can name the file without the pipeline holding the path. The
        # client-landmark path has no server-side file at all, and both paths feed the same
        # reporting code.
        filename=path.name,
        codec=codec,
        width=width,
        height=height,
        fps=fps,
        duration_s=duration_s,
        frame_count=frame_count,
        rotation_deg=rotation,
        is_portrait=height > width,
    )


if __name__ == "__main__":  # quick manual check
    import sys
    print(json.dumps(probe(sys.argv[1]).to_dict(), indent=2))
