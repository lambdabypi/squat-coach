"""Pipeline orchestration: video in, report and overlay out.

Stages, in order, with the progress fractions the UI shows:
    probe -> pose+bar (one decode pass) -> reps -> quality -> rules -> agent -> overlay

The agent stage is optional and degrades cleanly: if it is unavailable, misconfigured or
returns something that fails validation, the deterministic verdicts ship with a note. The
system's job is to say something true, not something fluent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np

from .skill.loader import load_skill
from .skill.rules import evaluate_all
from .skill.summary import build_summary
from .vision.bar import BarDetector
from .vision.metrics import Measurement
from .vision.pose import extract_pose, pose_track_from_client
from .vision.probe import probe
from .vision.quality import assess_quality
from .vision.reps import segment_reps
from .vision.target_pose import solve_target_pose
from .vision.smoothing import angle_from_horizontal, interpolate_gaps, smooth

Progress = Callable[[str, float], None]

# Weights for the progress bar, roughly proportional to wall time.
STAGES = {
    "Checking the video": (0.00, 0.03),
    "Tracking the movement": (0.03, 0.72),
    "Finding repetitions": (0.72, 0.78),
    "Checking evidence quality": (0.78, 0.82),
    "Measuring against the standards": (0.82, 0.88),
    "Writing the assessment": (0.88, 0.99),
}

OVERLAY_JOINTS = ["shoulder", "hip", "knee", "ankle", "heel", "toe", "nose", "ear"]
SKELETON = [("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle"), ("ankle", "toe"), ("ankle", "heel")]


def _p(progress: Progress | None, stage: str, frac: float = 1.0) -> None:
    if progress is None:
        return
    lo, hi = STAGES.get(stage, (0.0, 1.0))
    progress(stage, lo + (hi - lo) * max(0.0, min(1.0, frac)))


def _clean(v) -> float | None:
    """NaN and infinity are not valid JSON."""
    return None if v is None or not np.isfinite(v) else round(float(v), 2)


def _joint_angle(a: np.ndarray, vertex: np.ndarray, b: np.ndarray) -> float | None:
    """Interior angle at `vertex` between rays to `a` and `b`, in degrees."""
    v1, v2 = a - vertex, b - vertex
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if not np.isfinite(n1) or not np.isfinite(n2) or n1 < 1e-6 or n2 < 1e-6:
        return None
    cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def _per_frame_angles(smoothed: dict, bar, shin_px: float, i: int) -> dict:
    """The measurements the assessment uses, exposed per frame so the player can show the
    system's reading of the movement as it happens rather than only at the bottom."""
    sh, hip = smoothed["shoulder"][i], smoothed["hip"][i]
    knee, ankle = smoothed["knee"][i], smoothed["ankle"][i]
    heel, toe = smoothed["heel"][i], smoothed["toe"][i]

    def ok(*pts) -> bool:
        return all(np.all(np.isfinite(p)) for p in pts)

    back = None
    if ok(sh, hip):
        back = float(angle_from_horizontal(hip, sh))

    bar_dev = None
    if bar is not None and ok(heel, toe) and np.isfinite(bar.x[i]) and shin_px > 0:
        midfoot_x = (heel[0] + toe[0]) / 2.0
        facing = np.sign(toe[0] - heel[0]) or 1.0
        bar_dev = float((bar.x[i] - midfoot_x) * facing / shin_px)

    return {
        "back": None if back is None else round(back, 1),
        "knee": None if not ok(hip, knee, ankle) else _r(_joint_angle(hip, knee, ankle)),
        "hip": None if not ok(sh, hip, knee) else _r(_joint_angle(sh, hip, knee)),
        "bar_dev": None if bar_dev is None else round(bar_dev, 3),
        "midfoot_x": None if not ok(heel, toe) else round(float((heel[0] + toe[0]) / 2.0), 1),
    }


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def build_overlay(track, bar, seg, info, skill) -> dict:
    """Per-frame drawing data for the canvas overlay, in video pixel coordinates.

    The frontend synchronises this to <video>.currentTime rather than re-encoding an
    annotated file - instant to produce, and scrubbable.
    """
    smoothed = {j: smooth(interpolate_gaps(track.joint(j)), track.fps) for j in OVERLAY_JOINTS}
    shin_px = track.shin_length_px()
    frames = []
    for i in range(track.n):
        joints = {}
        for j in OVERLAY_JOINTS:
            x, y = smoothed[j][i]
            joints[j] = {
                "x": _clean(x), "y": _clean(y),
                "v": round(float(track.vis[j][i]), 2),
                "visible": bool(track.vis[j][i] > 0.6),
            }
        frames.append({
            "frame": i,
            "t": round(i / track.fps, 3),
            "joints": joints,
            "angles": _per_frame_angles(smoothed, bar, shin_px, i),
            "bar": {
                "x": _clean(bar.x[i]) if bar else None,
                "y": _clean(bar.y[i]) if bar else None,
                "observed": bool(bar.basis_observed[i]) if bar else False,
            },
        })

    bar_path = [
        {"t": round(i / track.fps, 3), "x": _clean(bar.x[i]), "y": _clean(bar.y[i]),
         "observed": bool(bar.basis_observed[i])}
        for i in range(track.n)
        if bar is not None and np.isfinite(bar.x[i])
    ]

    return {
        "width": track.width,
        "height": track.height,
        "fps": track.fps,
        "duration_s": info.duration_s,
        "side": track.side,
        "shin_length_px": round(shin_px, 1) if np.isfinite(shin_px) else None,
        "skeleton": SKELETON,
        "frames": frames,
        "bar_path": bar_path,
        "reps": [r.to_dict() for r in seg.reps],
        # Reference values read from the skill, so the live display shows the same standard the
        # assessment uses. Each carries its provenance: the UI must not present our measurement
        # tolerance as something the document requires.
        "targets": _targets(skill),
    }


STANDARD_PLATE_DIAMETER_MM = 450.0   # competition bumper plate, the usual 45 lb / 20 kg disc


def _real_world_scale(bar) -> dict | None:
    """Millimetres per pixel, from the detected plate.

    Shin-lengths are the right internal unit because they are intrinsic to the athlete, but
    nobody thinks in them. A competition bumper plate is 450 mm across, so a detected plate is a
    ruler lying in the frame.

    This is an assumption, not a measurement: change plates and older iron are smaller, and a
    non-standard plate scales every centimetre figure with it. It is returned with the assumption
    attached so the interface can show it, and the normalised value stays the primary figure.
    """
    if bar is None or not bar.any_tracked or bar.observed_fraction < 0.3:
        return None
    if not np.isfinite(bar.median_radius) or bar.median_radius <= 0:
        return None
    return {
        "mm_per_px": round(STANDARD_PLATE_DIAMETER_MM / (2 * bar.median_radius), 4),
        "basis": "barbell_plate",
        "assumption": (
            f"Assumes a standard {STANDARD_PLATE_DIAMETER_MM:.0f} mm competition plate. "
            "Centimetre figures scale with that assumption; the shin-length figures do not."
        ),
        "confidence": "medium" if bar.observed_fraction > 0.6 else "low",
    }


def _targets(skill) -> dict:
    out: dict = {}
    for cid, key in (("back_angle", "back"), ("bar_path_over_midfoot", "bar_dev")):
        try:
            c = skill.by_id(cid)
        except KeyError:
            continue
        out[key] = {
            "reference": c.rule.reference_value if c.rule else None,
            "tolerance": c.tolerance.value if c.tolerance else None,
            "tolerance_provenance": c.tolerance.provenance.value if c.tolerance else None,
            "unit": c.measure.unit if c.measure else None,
            "citation": c.source.citation(),
        }
    return out


PREVIEW_JOINTS = {
    "shoulder": (11, 12), "hip": (23, 24), "knee": (25, 26),
    "ankle": (27, 28), "heel": (29, 30), "toe": (31, 32),
}
PREVIEW_EVERY = 2   # frames; enough for the preview to look continuous without flooding polls


def _preview_payload(idx: int, lms, side_right: bool) -> dict:
    """A compact landmark snapshot in normalised coordinates, for the live view."""
    out: dict = {"frame": idx, "joints": {}}
    if lms is None:
        return out
    for name, (li, ri) in PREVIEW_JOINTS.items():
        lm = lms[ri if side_right else li]
        out["joints"][name] = [round(lm.x, 4), round(lm.y, 4), round(lm.visibility, 2)]
    return out


def analyse(
    video_path: str | Path,
    use_agent: bool = True,
    progress: Progress | None = None,
    preview: Callable[[dict], None] | None = None,
) -> dict:
    video_path = Path(video_path)
    skill = load_skill()

    # 1. Probe -------------------------------------------------------------
    _p(progress, "Checking the video", 0.0)
    info = probe(video_path)
    _p(progress, "Checking the video", 1.0)

    # 2. Pose + bar, in a single decode pass --------------------------------
    # The bar detector and the live preview both ride on this one decode; nothing re-reads
    # the file.
    detector = BarDetector()

    def sink(idx: int, frame, lms) -> None:
        detector.feed(idx, frame, lms)
        if preview is not None and idx % PREVIEW_EVERY == 0:
            # Side is not yet decided at this point (it needs the whole clip), so the preview
            # shows the left chain. It is a progress view, not evidence.
            preview(_preview_payload(idx, lms, side_right=False))

    track = extract_pose(
        video_path, info.fps,
        progress=lambda f: _p(progress, "Tracking the movement", f),
        frame_sink=sink,
    )
    bar = detector.finalise()

    return _assess_track(track, bar, info, skill, use_agent, progress)


def analyse_client_landmarks(
    payload: dict,
    frames: dict[int, "np.ndarray"],
    use_agent: bool = True,
    progress: Progress | None = None,
) -> dict:
    """Assess from landmarks computed in the browser, plus a decimated set of frames.

    Why this exists: the same image that tracks at 4.1 frames per second on a developer laptop
    managed 0.41 on Cloud Run, and raising the vCPU allocation made it worse. The container was
    not misconfigured - it reported 4 CPUs and used 4 threads - the shared vCPUs are simply much
    slower per core, which is not something a flag can fix.

    So pose moves to the device that already has fast hardware: the user's own. What does NOT
    move is the measurement layer. Everything below this function is the same code the local
    build runs, so the verified numbers stay comparable. Reimplementing smoothing, repetition
    detection, the metrics and the inverse-kinematics solve in JavaScript would have produced a
    second implementation with its own answers, which is how a subtly different OpenCV version
    once returned 12/6/4 where the verified build returns 13/6/3.

    Barbell detection still needs pixels, so the client uploads a decimated set of frames and
    HoughCircles runs on those alone. Every frame still contributes its shoulder position, so
    frames without an image fall back to the labelled `estimated` bar position exactly as they
    do when a plate is missed in the full-decode path.
    """
    skill = load_skill()

    video = payload["video"]
    info = SimpleNamespace(
        path="client",
        filename=video.get("filename", "client-upload"),
        codec=video.get("codec", "client"),
        width=int(video["width"]),
        height=int(video["height"]),
        fps=float(video["fps"]),
        duration_s=float(video["duration_s"]),
        frame_count=int(video.get("frame_count", 0)),
        rotation_deg=0,
        is_portrait=int(video["height"]) > int(video["width"]),
    )

    _p(progress, "Checking the video", 1.0)

    track = pose_track_from_client(
        payload["frames"], info.fps, info.width, info.height,
    )

    # Barbell detection over the uploaded frames only.
    _p(progress, "Tracking the movement", 0.2)
    detector = BarDetector(width=info.width, height=info.height)
    raw = _client_landmark_objects(payload["frames"], track.n)
    for i in range(track.n):
        detector.feed(i, frames.get(i), raw[i])
        if progress and track.n:
            _p(progress, "Tracking the movement", 0.2 + 0.8 * (i + 1) / track.n)
    bar = detector.finalise()

    return _assess_track(track, bar, info, skill, use_agent, progress)


class _LM:
    """Minimal stand-in for a MediaPipe landmark, so BarDetector needs no changes."""

    __slots__ = ("x", "y", "visibility")

    def __init__(self, x: float, y: float, v: float) -> None:
        self.x, self.y, self.visibility = x, y, v


def _client_landmark_objects(frames: list[dict], n: int) -> list[list | None]:
    """Rebuild index-addressable landmark lists from the client payload."""
    out: list[list | None] = [None] * n
    for f in frames:
        i = int(f["i"])
        lm = f.get("lm") or {}
        if not lm or i >= n:
            continue
        # 33 slots so BarDetector's fixed indices resolve.
        row: list = [_LM(0.0, 0.0, 0.0) for _ in range(33)]
        for key, v in lm.items():
            k = int(key)
            if 0 <= k < 33 and v and len(v) >= 3:
                row[k] = _LM(float(v[0]), float(v[1]), float(v[2]))
        out[i] = row
    return out


def _assess_track(track, bar, info, skill, use_agent: bool, progress: Progress | None) -> dict:
    """Everything after tracking. Shared by the server-side and client-side entry points so
    there is exactly one implementation of the measurements."""
    # 3. Reps ---------------------------------------------------------------
    _p(progress, "Finding repetitions", 0.0)
    seg = segment_reps(track)
    _p(progress, "Finding repetitions", 1.0)

    # 4. Quality gates -------------------------------------------------------
    _p(progress, "Checking evidence quality", 0.0)
    quality = assess_quality(track, seg, bar)
    _p(progress, "Checking evidence quality", 1.0)

    # 5. Deterministic rules --------------------------------------------------
    _p(progress, "Measuring against the standards", 0.0)
    candidates = evaluate_all(skill, track, seg.reps, bar, quality)

    # 5b. A corrected pose per repetition, for the criteria that actually failed.
    #
    # Borderline counts as worth correcting: a depth result inside the tolerance is precisely
    # the case where showing the athlete the target position is most useful.
    targets_by_rep: dict[int, dict] = {}
    correctable = {"depth", "back_angle"}
    back_ref = 45.0
    knee_limit = 0.5
    try:
        back_ref = skill.by_id("back_angle").rule.reference_value or 45.0
    except KeyError:
        pass
    try:
        kt = skill.by_id("knee_forward_of_toes").tolerance
        knee_limit = kt.value if kt else knee_limit
    except KeyError:
        pass
    for rep in seg.reps:
        failed = {
            c.criterion_id for c in candidates
            if c.rep_index == rep.index
            and c.criterion_id in correctable
            and c.verdict in ("does_not_meet_standard", "cannot_assess")
            and c.measurement is not None and c.measurement.available
        }
        if not failed:
            continue
        tp = solve_target_pose(track, rep, bar, failed, back_ref, knee_limit)
        if tp is not None:
            targets_by_rep[rep.index] = tp.to_dict()
    _p(progress, "Measuring against the standards", 1.0)

    # 6. Agent ----------------------------------------------------------------
    # The summary is built here, from the counted findings, whether or not the agent runs.
    summary = build_summary(skill, candidates, len(seg.reps), quality) if candidates else None
    cost = None
    agent_note = None

    # A blocked analysis must say so in words, not present an empty findings list. This is the
    # "not enough information" path the brief asks us to describe: we state what was wrong, what
    # it prevents, and what to change about the recording.
    if not quality.is_assessable:
        reasons = [g.detail for g in quality.blocking]
        summary = (
            "This video could not be assessed. "
            + " ".join(reasons)
            + " No repetition was judged against the reference standards, because doing so would "
              "mean reporting conclusions the footage does not support."
        )
        return {
            "report": {
                "video": {
                    "filename": info.filename,
                    "width": info.width, "height": info.height,
                    "fps": info.fps, "duration_s": info.duration_s,
                    "frame_count": info.frame_count, "codec": info.codec,
                },
                "skill": {
                    "version": skill.meta.skill_version,
                    "document": skill.meta.document_title,
                    "source": skill.meta.document_source,
                },
                "pose": {
                    "side": track.side,
                    "side_confidence": round(track.side_confidence, 3),
                    "shin_length_px": round(track.shin_length_px(), 1),
                    "detection_fraction": round(float(track.detected.mean()), 3),
                },
                "bar": {
                    "observed_fraction": round(bar.observed_fraction, 3),
                    "median_radius_px": _clean(bar.median_radius),
                    "note": bar.note,
                },
                "quality": quality.to_dict(),
                "reps": [r.to_dict() for r in seg.reps],
                "rep_note": seg.note,
                "coverage": skill.coverage_rows(),
                "findings": [],
                "summary": summary,
                "blocked": True,
                "agent_note": None,
                "cost": None,
            },
            "overlay": build_overlay(track, bar, seg, info, skill),
        }

    findings = [
        {
            **c.to_dict(),
            "explanation": c.reason,
            "feedback": c.feedback_source if c.verdict == "does_not_meet_standard" else None,
            "timestamp_s": (c.measurement.t if c.measurement and c.measurement.t is not None
                            else next((r.bottom_t for r in seg.reps if r.index == c.rep_index), None)),
            "frame_index": (c.measurement.frame if c.measurement else None),
            "narrated_by": "rules",
        }
        for c in candidates
    ]

    if use_agent and candidates:
        _p(progress, "Writing the assessment", 0.0)
        try:
            from .agent.assess import assess_with_agent
            agent_out = assess_with_agent(skill, candidates, seg.reps, quality, info)
            findings = agent_out["findings"]
            cost = agent_out["cost"]
            agent_note = agent_out.get("note")
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
            agent_note = (f"The language model stage was unavailable ({type(exc).__name__}: {exc}). "
                          "Verdicts and measurements below come from the deterministic rule "
                          "engine and are unaffected; only the wording is plainer.")
        _p(progress, "Writing the assessment", 1.0)
    elif not use_agent:
        agent_note = "Run with --no-agent: deterministic rule engine only, no language model involved."

    report = {
        "video": {
            "filename": info.filename,
            "width": info.width, "height": info.height,
            "fps": info.fps, "duration_s": info.duration_s,
            "frame_count": info.frame_count, "codec": info.codec,
        },
        "skill": {
            "version": skill.meta.skill_version,
            "document": skill.meta.document_title,
            "source": skill.meta.document_source,
        },
        "pose": {
            "side": track.side,
            "side_confidence": round(track.side_confidence, 3),
            "shin_length_px": round(track.shin_length_px(), 1),
            "detection_fraction": round(float(track.detected.mean()), 3),
        },
        "bar": {
            "observed_fraction": round(bar.observed_fraction, 3),
            "median_radius_px": _clean(bar.median_radius),
            "note": bar.note,
        },
        "scale": _real_world_scale(bar),
        "quality": quality.to_dict(),
        "reps": [r.to_dict() for r in seg.reps],
        "rep_note": seg.note,
        "coverage": skill.coverage_rows(),
        "findings": findings,
        "summary": summary,
        "blocked": False,
        "agent_note": agent_note,
        "cost": cost,
    }

    overlay = build_overlay(track, bar, seg, info, skill)
    overlay["target_poses"] = targets_by_rep
    return {"report": report, "overlay": overlay}
