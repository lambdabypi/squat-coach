"""The assessment agent.

One tool call, all repetitions at once, with the skill in a cached prompt block. The agent's
output is validated against the evidence it was given, and any finding that fails validation is
replaced by the deterministic one rather than discarded silently.

The guard that matters: the agent may move a verdict toward `cannot_assess`, never away from it.
A model that talks itself into confidence is the exact failure this application is supposed to
avoid.
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..skill.rules import FAILS, MEETS, UNKNOWN, Candidate
from .prompts import SYSTEM, evidence_block, skill_block

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000

# Published per-million-token prices for the model above, used for the cost estimate we report.
PRICE_IN_PER_MTOK = 3.00
PRICE_OUT_PER_MTOK = 15.00
PRICE_CACHE_READ_PER_MTOK = 0.30

TOOL = {
    "name": "submit_assessment",
    "description": "Submit the finished assessment: one finding per candidate, plus a summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rep_index": {"type": "integer"},
                        "criterion_id": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": [MEETS, FAILS, UNKNOWN],
                        },
                        "explanation": {
                            "type": "string",
                            "description": "One or two plain sentences. Cite only supplied numbers.",
                        },
                        "feedback": {
                            "type": ["string", "null"],
                            "description": "Actionable coaching, grounded in feedback_source. "
                                           "Null unless the verdict is does_not_meet_standard.",
                        },
                        "uncertainty": {
                            "type": ["string", "null"],
                            "description": "What genuinely qualifies this conclusion, or null.",
                        },
                    },
                    "required": ["rep_index", "criterion_id", "verdict", "explanation"],
                },
            },
            "summary": {"type": "string", "description": "2-4 sentences for the whole video."},
        },
        "required": ["findings", "summary"],
    },
}


class AgentFinding(BaseModel):
    rep_index: int
    criterion_id: str
    verdict: str
    explanation: str = Field(min_length=10)
    feedback: str | None = None
    uncertainty: str | None = None


class AgentOutput(BaseModel):
    findings: list[AgentFinding]
    summary: str = Field(min_length=20)


# Ordered by confidence. The agent may only move down this list, never up.
_CONFIDENCE_RANK = {UNKNOWN: 0, MEETS: 1, FAILS: 1}


def _candidate_dict(c: Candidate) -> dict[str, Any]:
    return {
        **c.to_dict(),
        "explanation": c.reason,
        "feedback": c.feedback_source if c.verdict == FAILS else None,
        "timestamp_s": c.measurement.t if c.measurement else None,
        "frame_index": c.measurement.frame if c.measurement else None,
        "narrated_by": "rules",
    }


def assess_with_agent(skill, candidates: list[Candidate], reps, quality, info) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    from anthropic import Anthropic

    client = Anthropic()
    messages = [{
        "role": "user",
        "content": [
            # Cached: identical for every video, so we pay full price once per session.
            {"type": "text", "text": skill_block(skill), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": evidence_block(candidates, reps, quality, info)},
        ],
    }]

    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "submit_assessment"},
        messages=messages,
    )

    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("the model did not call submit_assessment")

    try:
        parsed = AgentOutput.model_validate(block.input)
    except ValidationError:
        # One repair attempt, showing the model its own error.
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": "That did not match the schema. Re-send submit_assessment with every "
                           "required field present and one finding per candidate.",
                "is_error": True,
            }]},
        ]
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[TOOL],
            tool_choice={"type": "tool", "name": "submit_assessment"}, messages=messages,
        )
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            raise RuntimeError("the model did not call submit_assessment on retry")
        parsed = AgentOutput.model_validate(block.input)

    by_key = {(f.rep_index, f.criterion_id): f for f in parsed.findings}
    findings: list[dict] = []
    overrides: list[str] = []
    missing = 0

    for c in candidates:
        base = _candidate_dict(c)
        af = by_key.get((c.rep_index, c.criterion_id))
        if af is None:
            missing += 1
            findings.append(base)
            continue

        verdict = af.verdict
        # The one-way guard: more caution is allowed, more confidence is not.
        if _CONFIDENCE_RANK.get(verdict, 1) > _CONFIDENCE_RANK.get(c.verdict, 1):
            overrides.append(
                f"rep {c.rep_index}/{c.criterion_id}: model proposed '{verdict}' where the rule "
                f"engine said '{c.verdict}'; kept the rule engine's verdict."
            )
            verdict = c.verdict
        elif verdict != c.verdict:
            overrides.append(
                f"rep {c.rep_index}/{c.criterion_id}: model reduced '{c.verdict}' to "
                f"'{verdict}' on the evidence; accepted."
            )

        findings.append({
            **base,
            "verdict": verdict,
            "explanation": af.explanation,
            "feedback": af.feedback if verdict == FAILS else None,
            "uncertainty": af.uncertainty or c.uncertainty,
            "narrated_by": "agent",
        })

    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    plain_in = u.input_tokens
    cost = (
        plain_in / 1e6 * PRICE_IN_PER_MTOK
        + cache_write / 1e6 * PRICE_IN_PER_MTOK * 1.25
        + cache_read / 1e6 * PRICE_CACHE_READ_PER_MTOK
        + u.output_tokens / 1e6 * PRICE_OUT_PER_MTOK
    )

    note = None
    parts = []
    if missing:
        parts.append(f"{missing} finding(s) were not returned by the model and fall back to the "
                     "rule engine's wording.")
    if overrides:
        parts.append("Verdict adjustments: " + " ".join(overrides))
    if parts:
        note = " ".join(parts)

    return {
        "findings": findings,
        "summary": parsed.summary,
        "note": note,
        "cost": {
            "model": MODEL,
            "input_tokens": plain_in,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "output_tokens": u.output_tokens,
            "estimated_usd": round(cost, 4),
        },
    }
