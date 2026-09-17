"""Pose landmark extraction.

Two decisions here carry the rest of the pipeline:

1. **Sequential reading, never seeking.** `cap.set(POS_FRAMES)` on VP9 costs ~1s per seek and
   dominated our first timing run. We read the file straight through, once.
2. **Near-side limb selection.** In a sagittal view the far leg is occluded by the near one, so
   its landmarks are low-visibility guesses. We pick the side the camera can actually see, by
   mean visibility over the whole clip, and measure on that side only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "pose_landmarker_heavy.task"

# BlazePose indices, per side.
LEFT = {"shoulder": 11, "elbow": 13, "hip": 23, "knee": 25, "ankle": 27, "heel": 29, "toe": 31, "ear": 7}
RIGHT = {"shoulder": 12, "elbow": 14, "hip": 24, "knee": 26, "ankle": 28, "heel": 30, "toe": 32, "ear": 8}
NOSE = 0

# Joints used to decide which side faces the camera. Legs dominate: they are what occlude.
SIDE_VOTE_JOINTS = ["knee", "ankle", "heel", "toe"]

VISIBILITY_FLOOR = 0.6  # engineering_tolerance, mirrored in the skill's landmark_visibility gate


@dataclass
class PoseTrack:
    """Per-frame landmark series for the camera-facing side, in pixel coordinates."""

    fps: float
    width: int
    height: int
    side: str                                   # "left" or "right"
    side_confidence: float                      # mean visibility margin that decided it
    frame_idx: np.ndarray                       # (N,)
    t: np.ndarray                               # (N,) seconds
    xy: dict[str, np.ndarray] = field(default_factory=dict)   # joint -> (N,2) pixels
    vis: dict[str, np.ndarray] = field(default_factory=dict)  # joint -> (N,) 0..1
    detected: np.ndarray | None = None          # (N,) bool, was a pose found at all
    both_hips_x: np.ndarray | None = None       # (N,2) left/right hip x, for the sagittal gate
    both_shoulders_x: np.ndarray | None = None  # (N,2)

    @property
    def n(self) -> int:
        return len(self.frame_idx)

    def joint(self, name: str) -> np.ndarray:
        return self.xy[name]

    def y(self, name: str) -> np.ndarray:
        return self.xy[name][:, 1]

    def x(self, name: str) -> np.ndarray:
        return self.xy[name][:, 0]

    def shin_length_px(self) -> float:
        """Median ankle->knee distance. Our normalising unit: intrinsic to the athlete,
        so measurements stay comparable across videos, framings and body sizes."""
        d = np.linalg.norm(self.xy["knee"] - self.xy["ankle"], axis=1)
        ok = (self.vis["knee"] > VISIBILITY_FLOOR) & (self.vis["ankle"] > VISIBILITY_FLOOR)
        usable = d[ok] if ok.sum() >= 5 else d
        return float(np.median(usable)) if len(usable) else float("nan")

    def visible(self, name: str, i: int) -> bool:
        return bool(self.vis[name][i] > VISIBILITY_FLOOR)

    def min_visibility(self, names: list[str], i: int) -> float:
        return float(min(self.vis[n][i] for n in names))


def _iter_frames(path: Path) -> Iterator[tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {path}")
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield i, frame
            i += 1
    finally:
        cap.release()


def extract_pose(
    video_path: str | Path,
    fps: float,
    progress: Callable[[float], None] | None = None,
    frame_sink: Callable[[int, np.ndarray, object], None] | None = None,
) -> PoseTrack:
    """Run pose over the whole clip in one sequential pass.

    `frame_sink` lets the bar tracker piggyback on the same decode pass — decoding twice
    would double the dominant cost of the pipeline.
    """
    video_path = Path(video_path)
    if not MODEL_PATH.exists():
        raise RuntimeError(f"Pose model missing at {MODEL_PATH}. Run scripts/fetch_model.py.")

    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    idxs: list[int] = []
    raw: list[object] = []        # landmark list per frame, or None
    width = height = 0
    total_hint = 0

    cap = cv2.VideoCapture(str(video_path))
    total_hint = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    cap.release()

    with PoseLandmarker.create_from_options(opts) as landmarker:
        for i, frame in _iter_frames(video_path):
            if height == 0:
                height, width = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(round(i * 1000.0 / fps))
            res = landmarker.detect_for_video(mp_img, ts_ms)
            lms = res.pose_landmarks[0] if res.pose_landmarks else None
            idxs.append(i)
            raw.append(lms)
            if frame_sink is not None:
                frame_sink(i, frame, lms)
            if progress and total_hint:
                progress(min(1.0, (i + 1) / total_hint))

    if not idxs:
        raise RuntimeError("No frames could be decoded from this video.")

    n = len(idxs)
    detected = np.array([lm is not None for lm in raw], dtype=bool)
    if detected.sum() == 0:
        raise RuntimeError("No person was detected in this video.")

    # Decide the camera-facing side from mean visibility of the occlusion-prone leg joints.
    def side_score(mapping: dict[str, int]) -> float:
        vals = []
        for j in SIDE_VOTE_JOINTS:
            k = mapping[j]
            vals.append(np.mean([lm[k].visibility for lm in raw if lm is not None]))
        return float(np.mean(vals))

    l_score, r_score = side_score(LEFT), side_score(RIGHT)
    side, mapping = ("left", LEFT) if l_score >= r_score else ("right", RIGHT)

    track = PoseTrack(
        fps=fps,
        width=width,
        height=height,
        side=side,
        side_confidence=abs(l_score - r_score),
        frame_idx=np.array(idxs),
        t=np.array(idxs) / fps,
        detected=detected,
    )

    joints = list(mapping.keys()) + ["nose"]
    for j in joints:
        track.xy[j] = np.full((n, 2), np.nan)
        track.vis[j] = np.zeros(n)
    track.both_hips_x = np.full((n, 2), np.nan)
    track.both_shoulders_x = np.full((n, 2), np.nan)

    for i, lms in enumerate(raw):
        if lms is None:
            continue
        for j in mapping:
            lm = lms[mapping[j]]
            track.xy[j][i] = (lm.x * width, lm.y * height)
            track.vis[j][i] = lm.visibility
        track.xy["nose"][i] = (lms[NOSE].x * width, lms[NOSE].y * height)
        track.vis["nose"][i] = lms[NOSE].visibility
        track.both_hips_x[i] = (lms[LEFT["hip"]].x * width, lms[RIGHT["hip"]].x * width)
        track.both_shoulders_x[i] = (lms[LEFT["shoulder"]].x * width, lms[RIGHT["shoulder"]].x * width)

    return track
