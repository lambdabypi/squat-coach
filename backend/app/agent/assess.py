"""The assessment agent.

One tool call, all repetitions at once, with the skill in its own prompt block. The agent's
output is validated against the evidence it was given, and any finding that fails validation is
replaced by the deterministic one rather than discarded silently.

The guard that matters: the agent may move a verdict toward `cannot_assess`, never away from it.
A model that talks itself into confidence is the exact failure this application is supposed to
avoid.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..config import env
from ..skill.rules import FAILS, MEETS, UNKNOWN, Candidate
from .prompts import SYSTEM, evidence_block, skill_block

# Haiku 4.5 by default: this stage does constrained work — judge a supplied measurement against
# a supplied rule, then write two sentences — so the cheapest current model is the right default.
# Override with ANTHROPIC_MODEL to compare quality against a larger model.
MODEL = env("ANTHROPIC_MODEL", "claude-haiku-4-5")
MAX_TOKENS = 8000

# Published per-million-token prices. Table-driven because an earlier hard-coded pair was wrong
# (Sonnet 5 priced at 3/15 when it is 2/10), which overstated the reported cost by ~50%.
# Cache writes bill at 1.25x input; cache reads at 0.1x input.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

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


def merge_verdict(rule_verdict: str, agent_verdict: str) -> tuple[str, bool]:
    """Decide the final verdict. Returns (verdict, was_the_agent_overridden).

    The agent may abstain — move a verdict to `cannot_assess` — and nothing else. It may not
    upgrade an abstention into a verdict, and it may not flip meets <-> does-not-meet: those
    two come from arithmetic on a measurement and a declared threshold, and the model has no
    information the rule engine lacks. Letting it disagree there would mean a language model
    overruling a comparison it cannot see better than the code that made it.
    """
    if agent_verdict == rule_verdict:
        return rule_verdict, False
    if agent_verdict == UNKNOWN:
        return UNKNOWN, False          # more caution is always allowed
    return rule_verdict, True          # anything else is discarded


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
    if not env("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    from anthropic import Anthropic

    # An organisation-scoped key must name the workspace it is acting for; a workspace-scoped
    # key must not. Which one a given key needs is not discoverable from the key itself, and
    # swapping keys flips the requirement — that cost a debugging round here, with the whole
    # agent stage silently falling back to the rule engine over one stale header.
    #
    # So: send the header when configured, and if the workspace turns out not to exist for this
    # key, retry once without it rather than losing the assessment. Surfaced in `agent_note`,
    # never silent.
    workspace = env("ANTHROPIC_WORKSPACE_ID")
    workspace_note: str | None = None

    def build_client(ws: str | None) -> Anthropic:
        return Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)

    client = build_client(workspace)
    messages = [{
        "role": "user",
        "content": [
            # Identical for every video, so it carries the cache breakpoint. Note that on
            # claude-haiku-4-5 this block (~2.1k tokens) is BELOW the minimum cacheable prefix,
            # so the breakpoint is silently ignored and cache_read stays 0 — verified in
            # scripts/test_cache.py. Harmless, and it starts paying off if the skill grows or a
            # larger model is configured.
            {"type": "text", "text": skill_block(skill), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": evidence_block(candidates, reps, quality, info)},
        ],
    }]

    def call(c: Anthropic):
        return c.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "submit_assessment"},
            messages=messages,
        )

    try:
        resp = call(client)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        stale_workspace = workspace and "not_found" in text and "orkspace" in text
        if not stale_workspace:
            raise
        # The configured workspace does not exist for this key — most likely the key was
        # replaced with a workspace-scoped one. Retry without the header.
        client = build_client(None)
        resp = call(client)
        workspace_note = (
            f"ANTHROPIC_WORKSPACE_ID is set to a workspace this API key cannot see, so the "
            f"header was dropped and the request retried without it. Blank that variable in "
            f".env — this key is workspace-scoped and does not need it."
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

        verdict, was_overridden = merge_verdict(c.verdict, af.verdict)
        if was_overridden:
            overrides.append(
                f"rep {c.rep_index}/{c.criterion_id}: model proposed '{af.verdict}' where the "
                f"rule engine said '{c.verdict}'; kept the rule engine's verdict."
            )
        elif verdict != c.verdict:
            overrides.append(
                f"rep {c.rep_index}/{c.criterion_id}: model abstained from '{c.verdict}' on the "
                "evidence; accepted."
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

    price = PRICING.get(MODEL)
    if price is None:
        cost = None  # unknown model: report tokens, never a fabricated dollar figure
    else:
        cost = (
            plain_in / 1e6 * price["input"]
            + cache_write / 1e6 * price["input"] * CACHE_WRITE_MULTIPLIER
            + cache_read / 1e6 * price["input"] * CACHE_READ_MULTIPLIER
            + u.output_tokens / 1e6 * price["output"]
        )

    note = None
    parts = []
    if workspace_note:
        parts.append(workspace_note)
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
            "estimated_usd": round(cost, 4) if cost is not None else None,
        },
    }
