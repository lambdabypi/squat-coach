"""Deterministic rule evaluation.

Produces a verdict and the evidence behind it for every (repetition x criterion) pair, using
only geometry and the thresholds declared in the skill. The agent receives this and may improve
the *wording* and the *grounding*; the verdicts here are the fallback if the agent is
unavailable or returns something that fails validation.

Three verdicts only, as the brief requires: meets_standard, does_not_meet_standard, cannot_assess.

Borderline results become `cannot_assess`, not a coin-flip. When a measurement sits inside the
measurement tolerance, we genuinely do not know which side of the line the athlete is on, and the
document's own standard is not precise enough to adjudicate it. An unassessable result is
preferable to invented precision.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Callable

from ..vision.bar import BarTrack
from ..vision.metrics import Measurement, compute
from ..vision.pose import PoseTrack
from ..vision.quality import QualityReport
from ..vision.reps import Rep
from .loader import Assessability, Criterion, Skill

MEETS = "meets_standard"
FAILS = "does_not_meet_standard"
UNKNOWN = "cannot_assess"


@dataclass
class Candidate:
    """A deterministic finding, before the agent phrases it."""

    rep_index: int
    criterion_id: str
    criterion_name: str
    verdict: str
    measurement: Measurement | None
    threshold_value: float | None
    threshold_provenance: str | None
    confidence: str
    reason: str                       # why this verdict, in plain terms
    citation: str
    source_pages: list[int] = field(default_factory=list)
    quote: str | None = None
    feedback_source: str | None = None
    uncertainty: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["measurement"] = self.measurement.to_dict() if self.measurement else None
        return d


def _cap(confidence: str, cap: str | None) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    if cap is None:
        return confidence
    return confidence if order[confidence] <= order[cap] else cap


# --------------------------------------------------------------------------
# One evaluator per criterion. Each returns (verdict, reason) given the value
# and the thresholds declared in the skill.
# --------------------------------------------------------------------------

def _eval_depth(v: float, c: Criterion) -> tuple[str, str]:
    tol = c.tolerance.value if c.tolerance else 0.0
    if v > tol:
        return MEETS, (f"The hip landmark is {v:.2f} shin-lengths below the knee at the bottom, "
                       "so the hip has passed below the top of the patella.")
    if v < -tol:
        return FAILS, (f"The hip landmark is {abs(v):.2f} shin-lengths above the knee at the bottom. "
                       "The hip did not reach below the top of the patella, so this is a partial squat.")
    return UNKNOWN, (f"The hip finished within {tol:.2f} shin-lengths of the knee "
                     f"({v:+.3f}), which is inside our measurement tolerance. Depth is too close "
                     "to call from this footage rather than clearly good or clearly short.")


def _eval_back_angle(v: float, c: Criterion) -> tuple[str, str]:
    ref = c.rule.reference_value if c.rule and c.rule.reference_value else 45.0
    tol = c.tolerance.value if c.tolerance else 15.0
    if abs(v - ref) <= tol:
        lean = ("toward the vertical end of" if v > ref + tol / 2
                else "toward the horizontal end of" if v < ref - tol / 2
                else "close to the centre of")
        return MEETS, (f"The back is {v:.0f} degrees from horizontal at the bottom, {lean} our "
                       f"+/-{tol:.0f} degree band around the document's 'about {ref:.0f} degrees'. "
                       "The document gives a reference posture, not a pass mark, so this is "
                       "within range rather than exactly correct.")
    if v > ref + tol:
        return FAILS, (f"The back is {v:.0f} degrees from horizontal, more vertical than the "
                       f"document's 'about {ref:.0f} degrees, not at all vertical'.")
    return FAILS, (f"The back is {v:.0f} degrees from horizontal, more horizontal than the "
                   f"document's 'about {ref:.0f} degrees'.")


def _eval_bar_path(v: float, c: Criterion) -> tuple[str, str]:
    tol = c.tolerance.value if c.tolerance else 0.15
    if v <= tol:
        return MEETS, (f"The bar stayed within {v:.2f} shin-lengths of the midfoot throughout, "
                       "close to the vertical path over the middle of the foot.")
    return FAILS, (f"The bar drifted up to {v:.2f} shin-lengths from the midfoot, beyond our "
                   f"{tol:.2f} allowance, so it left the balance point during the lift.")


def _eval_hip_drive(v: float, c: Criterion) -> tuple[str, str]:
    tol = c.tolerance.value if c.tolerance else 0.15
    if v >= 1.0 + tol:
        return MEETS, (f"The hips rose {v:.2f} times as fast as the shoulders out of the bottom, "
                       "so the hips led the ascent.")
    if v < 1.0 - tol:
        return FAILS, (f"The shoulders rose faster than the hips out of the bottom "
                       f"(ratio {v:.2f}), which is lifting the chest rather than driving the hips.")
    return UNKNOWN, (f"Hips and shoulders rose at nearly the same rate (ratio {v:.2f}), inside our "
                     "measurement tolerance. This is too close to call.")


def _eval_knee_toe(v: float, c: Criterion) -> tuple[str, str]:
    tol = c.tolerance.value if c.tolerance else 0.5
    if 0 <= v <= tol:
        return MEETS, (f"At the bottom the knee is {v:.2f} shin-lengths forward of the toe, "
                       "matching 'just a little forward of the toes'.")
    if v < 0:
        return FAILS, (f"At the bottom the knee is {abs(v):.2f} shin-lengths behind the toe, further "
                       "back than the document's bottom position.")
    return FAILS, (f"At the bottom the knee is {v:.2f} shin-lengths forward of the toe, further "
                   "forward than 'just a little'.")


def _eval_heels(v: float, c: Criterion) -> tuple[str, str]:
    tol = c.tolerance.value if c.tolerance else 0.08
    if v <= tol:
        return MEETS, f"The heel stayed down; it moved {v:.2f} shin-lengths from its standing height."
    return FAILS, (f"The heel rose {v:.2f} shin-lengths from its standing height, so the feet did "
                   "not stay flat on the ground.")


def _eval_gaze(v: float, c: Criterion) -> tuple[str, str]:
    # Positive pitch = nose below ear = head down.
    if v > 10:
        return MEETS, f"The head is pitched down ({v:.0f} degrees), consistent with looking at the floor."
    if v < -15:
        return FAILS, (f"The head is pitched up ({abs(v):.0f} degrees), which the document identifies "
                       "as killing hip drive.")
    return UNKNOWN, (f"Head pitch is {v:+.0f} degrees, close to level. Gaze direction cannot be "
                     "determined from head orientation alone at this angle.")


def _eval_bar_placement(v: float, c: Criterion) -> tuple[str, str]:
    # Deliberately always cannot_assess.
    #
    # An earlier version failed any bar sitting more than 0.15 shin-lengths above the shoulder
    # landmark and called it "high-bar". That fires on essentially every video, because the pose
    # model's shoulder landmark is the shoulder JOINT CENTRE while a correctly placed low bar
    # rides well above it on the posterior deltoids. The threshold was measuring anatomy, not a
    # fault, and we have no labelled low-bar/high-bar footage to calibrate a real one against.
    #
    # The document's standard is anatomical - "right below the spine of the scapula" - and the
    # difference between correct and incorrect is roughly two centimetres on the athlete. We
    # report the measurement as evidence and decline the verdict.
    return UNKNOWN, (
        f"The bar centre sits {abs(v):.2f} shin-lengths {'above' if v < 0 else 'below'} the "
        "shoulder landmark. That measurement is real, but it cannot be turned into a verdict: "
        "pose estimation provides no scapular-spine landmark, and correct versus incorrect bar "
        "placement differs by roughly two centimetres on the athlete. We have no calibrated basis "
        "for a threshold here, so we decline to guess."
    )


EVALUATORS: dict[str, Callable[[float, Criterion], tuple[str, str]]] = {
    "depth": _eval_depth,
    "back_angle": _eval_back_angle,
    "bar_path_over_midfoot": _eval_bar_path,
    "hip_drive": _eval_hip_drive,
    "knee_forward_of_toes": _eval_knee_toe,
    "heels_flat": _eval_heels,
    "eye_gaze": _eval_gaze,
    "bar_placement_low_bar": _eval_bar_placement,
}


def evaluate_rep(
    skill: Skill,
    track: PoseTrack,
    rep: Rep,
    bar: BarTrack | None,
    quality: QualityReport,
) -> list[Candidate]:
    out: list[Candidate] = []

    for c in skill.criteria:
        base = dict(
            rep_index=rep.index,
            criterion_id=c.id,
            criterion_name=c.name,
            citation=c.source.citation(),
            source_pages=c.source.pages,
            quote=" ".join((c.source.quote or "").split()) or None,
            feedback_source=" ".join(c.feedback_on_fail.text.split()) if c.feedback_on_fail else None,
        )

        # Structurally unassessable from a side view — always, and we say what is needed.
        if c.assessable_from_side_view is Assessability.NONE:
            out.append(Candidate(
                **base, verdict=UNKNOWN, measurement=None,
                threshold_value=None, threshold_provenance=None, confidence="high",
                reason=" ".join((c.unassessable_reason or "").split()),
                uncertainty=f"Needed to assess this: {c.what_would_be_needed}",
            ))
            continue

        m: Measurement = compute(c.measure.id, track, rep, bar)
        tol_v = c.tolerance.value if c.tolerance else None
        tol_p = c.tolerance.provenance.value if c.tolerance else None

        if not m.available:
            out.append(Candidate(
                **base, verdict=UNKNOWN, measurement=m,
                threshold_value=tol_v, threshold_provenance=tol_p,
                confidence="high",
                reason=f"This could not be measured because {m.reason}.",
                uncertainty=m.reason,
            ))
            continue

        verdict, reason = EVALUATORS[c.id](float(m.value), c)
        confidence = _cap(m.confidence, c.confidence_cap)

        # An estimated bar position cannot support a confident bar-path verdict.
        if c.id == "bar_path_over_midfoot" and m.basis == "estimated":
            verdict = UNKNOWN
            reason = ("The barbell could not be tracked in pixels for most of this repetition, so "
                      "bar position is inferred from the shoulder. That is not firm enough evidence "
                      "to judge the bar path against the midfoot.")
            confidence = "high"

        uncertainty = m.reason
        degraded = [g for g in quality.gates if g.severity == "degraded" and not g.passed]
        if c.id in {"back_angle", "knee_forward_of_toes"} and quality.view_ratio > 0.25:
            note = ("The camera is only roughly side-on, which foreshortens the movement plane and "
                    "biases angle measurements.")
            uncertainty = f"{uncertainty} {note}".strip() if uncertainty else note
            confidence = _cap(confidence, "medium")
        if rep.confidence == "low":
            confidence = _cap(confidence, "low")

        out.append(Candidate(
            **base, verdict=verdict, measurement=m,
            threshold_value=tol_v, threshold_provenance=tol_p,
            confidence=confidence, reason=reason, uncertainty=uncertainty,
        ))

    return out


def evaluate_all(
    skill: Skill,
    track: PoseTrack,
    reps: list[Rep],
    bar: BarTrack | None,
    quality: QualityReport,
) -> list[Candidate]:
    if not quality.is_assessable:
        return []
    return [cand for rep in reps for cand in evaluate_rep(skill, track, rep, bar, quality)]
