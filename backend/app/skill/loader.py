"""Load and validate the document-derived skill.

The skill is the contract between the reference document and the assessment. It is validated
strictly at startup so that a malformed edit fails loudly at load time rather than quietly
producing ungrounded findings at assessment time — the reviewer is expected to edit this file
live, so a typo must be an error, not a silent behaviour change.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

SKILL_PATH = Path(__file__).resolve().parents[3] / "skill" / "squat_standards.yaml"


class Provenance(str, Enum):
    """Where a number came from. The single most important field in this file."""

    DOCUMENT = "document_stated"
    ENGINEERING = "engineering_tolerance"


class Assessability(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class SourceRef(BaseModel):
    pages: list[int] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    quote: str | None = None
    supporting_quote: str | None = None
    failure_quote: str | None = None
    midfoot_definition_quote: str | None = None
    note: str | None = None

    def citation(self) -> str:
        parts = []
        if self.pages:
            parts.append("ref p. " + ", ".join(str(p) for p in self.pages))
        if self.figures:
            parts.append("Fig " + ", ".join(self.figures))
        return " · ".join(parts) or "no citation"


class Measure(BaseModel):
    id: str
    description: str
    unit: str


class Rule(BaseModel):
    meets_when: str | None = None
    reference_value: float | None = None
    provenance: Provenance
    note: str | None = None


class Tolerance(BaseModel):
    value: float
    unit: str
    provenance: Provenance
    rationale: str | None = None

    @model_validator(mode="after")
    def tolerances_are_ours(self):
        # A tolerance is a measurement margin. The document states none, so a tolerance claiming
        # document provenance is always a mistake — most likely a bad edit. Fail loudly.
        if self.provenance is Provenance.DOCUMENT:
            raise ValueError(
                "A tolerance may not claim document_stated provenance. The reference document "
                "states no numeric margins; tolerances are engineering choices."
            )
        return self


class Feedback(BaseModel):
    pages: list[int] = Field(default_factory=list)
    text: str


class Uncertainty(BaseModel):
    cannot_assess_when: list[str] = Field(default_factory=list)
    degraded_when: list[str] = Field(default_factory=list)


class SystematicBias(BaseModel):
    description: str


class Criterion(BaseModel):
    id: str
    name: str
    checklist_heading: str | None = None
    assessable_from_side_view: Assessability
    source: SourceRef
    requires_landmarks: list[str] = Field(default_factory=list)
    measure: Measure | None = None
    rule: Rule | None = None
    tolerance: Tolerance | None = None
    feedback_on_fail: Feedback | None = None
    uncertainty: Uncertainty | None = None
    systematic_bias: SystematicBias | None = None
    partial_reason: str | None = None
    confidence_cap: Literal["high", "medium", "low"] | None = None
    unassessable_reason: str | None = None
    what_would_be_needed: str | None = None
    important_scope_note: str | None = None
    note_for_user: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        a = self.assessable_from_side_view
        if a is Assessability.NONE:
            if not self.unassessable_reason:
                raise ValueError(f"{self.id}: assessable 'none' requires unassessable_reason")
            if self.measure is not None:
                raise ValueError(f"{self.id}: assessable 'none' must not define a measure")
        else:
            if self.measure is None:
                raise ValueError(f"{self.id}: assessable '{a.value}' requires a measure")
            if self.rule is None:
                raise ValueError(f"{self.id}: assessable '{a.value}' requires a rule")
        if a is Assessability.PARTIAL and not self.partial_reason:
            raise ValueError(f"{self.id}: assessable 'partial' requires partial_reason")
        if not self.source.pages:
            raise ValueError(f"{self.id}: every criterion must cite at least one source page")
        return self

    @property
    def is_assessable(self) -> bool:
        return self.assessable_from_side_view is not Assessability.NONE


class GlobalGate(BaseModel):
    id: str
    description: str
    threshold: float | None = None
    provenance: Provenance | None = None
    on_fail: str
    document_basis: SourceRef | None = None


class SkillMeta(BaseModel):
    document_title: str
    document_source: str
    page_offset_note: str | None = None
    skill_version: str
    coordinate_convention: str | None = None
    checklist_origin: SourceRef | None = None


class Skill(BaseModel):
    meta: SkillMeta
    criteria: list[Criterion]
    global_gates: list[GlobalGate]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [c.id for c in self.criteria]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate criterion ids: {sorted(dupes)}")
        return self

    def by_id(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    @property
    def assessable(self) -> list[Criterion]:
        return [c for c in self.criteria if c.is_assessable]

    @property
    def unassessable(self) -> list[Criterion]:
        return [c for c in self.criteria if not c.is_assessable]

    def coverage_rows(self) -> list[dict]:
        """Feeds the UI's coverage table — stated up front, not buried."""
        return [
            {
                "id": c.id,
                "name": c.name,
                "assessable": c.assessable_from_side_view.value,
                "citation": c.source.citation(),
                "reason": c.unassessable_reason or c.partial_reason,
                "needed": c.what_would_be_needed,
            }
            for c in self.criteria
        ]


def load_skill(path: Path | str = SKILL_PATH) -> Skill:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    return Skill.model_validate(yaml.safe_load(text))


if __name__ == "__main__":
    s = load_skill()
    print(f"skill v{s.meta.skill_version} — {s.meta.document_title}")
    print(f"{len(s.criteria)} criteria, {len(s.global_gates)} global gates\n")
    for c in s.criteria:
        rule_p = c.rule.provenance.value if c.rule else "-"
        tol_p = c.tolerance.provenance.value if c.tolerance else "-"
        print(f"  {c.id:26s} {c.assessable_from_side_view.value:7s} "
              f"rule={rule_p:17s} tol={tol_p:21s} {c.source.citation()}")
    print(f"\nassessable: {len(s.assessable)} | not assessable from side view: {len(s.unassessable)}")
    for c in s.unassessable:
        print(f"  ! {c.name}: {c.what_would_be_needed}")
