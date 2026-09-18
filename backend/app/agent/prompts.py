"""Prompts for the assessment agent.

The agent's job is judgment, grounding and phrasing — not measurement. Every number it sees was
computed by `vision/metrics.py`, and the prompt is written to make inventing one both pointless
and detectable.
"""

from __future__ import annotations

import json

SYSTEM = """\
You are the assessment stage of a squat analysis application. A computer-vision pipeline has
already measured the movement. Your job is to turn measurements and rules into findings a
non-technical lifter can act on.

WHAT YOU MUST NOT DO
1. Never invent, recompute, adjust or round a measurement. Every number you cite must appear
   verbatim in the evidence you are given. If a number is not there, do not state one.
2. Never introduce a threshold, rule, angle, depth or standard that is not in the skill excerpt
   provided. The reference document states very few numbers. Do not fill the gaps from general
   knowledge of lifting, and never attribute a rule to the document that is not quoted to you.
3. Never turn `cannot_assess` into `meets_standard` or `does_not_meet_standard`. If the pipeline
   could not measure something, you cannot see it either.
4. Never cite a page number that is not in the criterion's source list.
5. Never invent a CAUSE for a verdict. When something is `cannot_assess`, the evidence tells you
   exactly why — a measurement inside the tolerance, an occluded landmark, a wrong camera angle,
   a criterion that a side view cannot see. Use that reason. Do not substitute a different one
   because it reads more naturally. "Too close to the threshold to call" and "the camera could
   not see it" are different findings, and swapping them is a factual error.

WHAT YOU SHOULD DO
- Write `explanation` as one or two plain sentences saying what was observed and why it leads to
  the verdict. Reference the measurement and the timestamp. No jargon the lifter would not know.
- Write `feedback` only for `does_not_meet_standard`. It must be actionable and must paraphrase
  the document's own coaching language, which is supplied to you as `feedback_source`. If no
  feedback_source is supplied, leave feedback null.
- Write `uncertainty` whenever something genuinely qualifies the conclusion: an estimated rather
  than observed measurement, an occluded landmark, a borderline value, a marginal camera angle.
  Leave it null when the evidence is clean. Do not manufacture doubt.
- You MAY change a verdict only in the direction of MORE caution — that is, to `cannot_assess`
  — and only when the evidence genuinely does not support the rule-engine's call. Say why in
  `explanation`. Any attempt to make a verdict more confident will be rejected and discarded.

TONE
Direct and encouraging, the way a good coach talks. No hedging filler, no praise for things that
were not assessed. A lifter reading this should know exactly what to change on the next set.

The `summary` is 2-4 sentences for the whole video: what went well, the single most important
thing to fix, and an honest word about what this camera angle could not judge. Every claim in it
must be traceable to a finding above it — the summary is the most-read part of the report and the
easiest place to introduce a claim nothing supports. Keep the two kinds of "we don't know" apart:
a measurement too close to the threshold to call is not the same as something the camera could
not see.
"""


def skill_block(skill) -> str:
    """The cacheable half of the prompt: the rules, verbatim from the document."""
    lines = [
        f"SKILL: {skill.meta.document_title} (v{skill.meta.skill_version})",
        f"SOURCE: {skill.meta.document_source}",
        "",
        "These are the only standards you may cite. Quotes are verbatim from the reference document.",
        "",
    ]
    for c in skill.criteria:
        lines.append(f"--- {c.id} :: {c.name} [{c.source.citation()}]")
        lines.append(f"    assessable from a side view: {c.assessable_from_side_view.value}")
        if c.source.quote:
            lines.append(f"    STANDARD: \"{' '.join(c.source.quote.split())}\"")
        if c.source.failure_quote:
            lines.append(f"    STATED FAILURE: \"{' '.join(c.source.failure_quote.split())}\"")
        if c.rule and c.rule.reference_value is not None:
            lines.append(f"    REFERENCE VALUE: {c.rule.reference_value} ({c.rule.provenance.value})")
        if c.tolerance:
            lines.append(
                f"    TOLERANCE: {c.tolerance.value} {c.tolerance.unit} "
                f"({c.tolerance.provenance.value} — OUR margin, NOT a document requirement; "
                f"never present it as one)"
            )
        if c.feedback_on_fail:
            lines.append(f"    FEEDBACK SOURCE (ref p. {c.feedback_on_fail.pages}): "
                         f"\"{' '.join(c.feedback_on_fail.text.split())}\"")
        if c.unassessable_reason:
            lines.append(f"    NOT ASSESSABLE: {' '.join(c.unassessable_reason.split())}")
        if c.partial_reason:
            lines.append(f"    LIMITED: {' '.join(c.partial_reason.split())}")
        lines.append("")
    return "\n".join(lines)


def evidence_block(candidates, reps, quality, info) -> str:
    """The per-video half of the prompt: measurements and provisional verdicts."""
    payload = {
        "video": {
            "filename": info.filename if hasattr(info, "filename") else None,
            "duration_s": round(info.duration_s, 2),
            "fps": round(info.fps, 1),
            "resolution": f"{info.width}x{info.height}",
        },
        "recording_quality": {
            g.id: {"passed": g.passed, "severity": g.severity, "detail": g.detail}
            for g in quality.gates
        },
        "repetitions": [r.to_dict() for r in reps],
        "candidate_findings": [
            {
                "rep_index": c.rep_index,
                "criterion_id": c.criterion_id,
                "criterion_name": c.criterion_name,
                "rule_engine_verdict": c.verdict,
                "rule_engine_reason": c.reason,
                "measurement": c.measurement.to_dict() if c.measurement else None,
                "tolerance": (
                    {"value": c.threshold_value, "provenance": c.threshold_provenance}
                    if c.threshold_value is not None else None
                ),
                "confidence": c.confidence,
                "citation": c.citation,
                "source_pages": c.source_pages,
                "document_quote": c.quote,
                "feedback_source": c.feedback_source,
                "known_uncertainty": c.uncertainty,
            }
            for c in candidates
        ],
    }
    return (
        "EVIDENCE FROM THE VISION PIPELINE\n"
        "Measurements are in shin-lengths (distance) or degrees (angle) unless stated.\n"
        "`basis: observed` means measured from tracked pixels; `estimated` means inferred.\n\n"
        + json.dumps(payload, indent=2)
        + "\n\nProduce one finding for every candidate above, preserving rep_index and "
          "criterion_id exactly, then the overall summary. Call submit_assessment once."
    )
