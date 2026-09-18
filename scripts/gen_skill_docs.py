"""Generate coverage.md and CITATIONS.md from the skill YAML.

Generated rather than hand-written so the prose cannot drift from the rules the system
actually runs. Re-run after editing squat_standards.yaml.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.skill.loader import Assessability, load_skill  # noqa: E402

BADGE = {
    Assessability.FULL: "**Yes**",
    Assessability.PARTIAL: "Partial",
    Assessability.NONE: "**No**",
}


def coverage_md(skill) -> str:
    n_full = sum(1 for c in skill.criteria if c.assessable_from_side_view is Assessability.FULL)
    n_part = sum(1 for c in skill.criteria if c.assessable_from_side_view is Assessability.PARTIAL)
    n_none = len(skill.unassessable)

    out = [
        "# Coverage: what a side view can and cannot judge",
        "",
        "<!-- GENERATED from squat_standards.yaml by scripts/gen_skill_docs.py. Do not edit. -->",
        "",
        f"Of **{len(skill.criteria)} criteria** drawn from the reference document: "
        f"**{n_full} fully assessable** from a single side-view video, "
        f"**{n_part} partially assessable**, and **{n_none} not assessable at all**.",
        "",
        "The document's own closing checklist (ref p.35) names eight faults. Three of those eight "
        "are invisible to a sagittal camera. This page exists so that absence is stated rather "
        "than inferred from a missing row.",
        "",
        "| Criterion | Side view | Source | Measured how / why not |",
        "|---|---|---|---|",
    ]
    for c in skill.criteria:
        if c.assessable_from_side_view is Assessability.NONE:
            detail = c.unassessable_reason
        elif c.assessable_from_side_view is Assessability.PARTIAL:
            detail = c.partial_reason
        else:
            detail = c.measure.description if c.measure else ""
        detail = " ".join((detail or "").split())
        out.append(f"| {c.name} | {BADGE[c.assessable_from_side_view]} | {c.source.citation()} | {detail} |")

    out += ["", "## What would be needed for the unassessable criteria", ""]
    for c in skill.unassessable:
        out += [
            f"### {c.name}",
            "",
            f"*{c.source.citation()}*",
            "",
            f"> {' '.join((c.source.quote or '').split())}",
            "",
            f"**Why not:** {' '.join((c.unassessable_reason or '').split())}",
            "",
            f"**Needed:** {c.what_would_be_needed}",
            "",
        ]
        if c.note_for_user:
            out += [f"**Note:** {' '.join(c.note_for_user.split())}", ""]

    out += ["## Confidence caps", ""]
    capped = [c for c in skill.criteria if c.confidence_cap]
    if capped:
        out += ["| Criterion | Capped at | Reason |", "|---|---|---|"]
        for c in capped:
            out.append(f"| {c.name} | {c.confidence_cap} | {' '.join((c.partial_reason or '').split())} |")
    out.append("")
    return "\n".join(out)


def citations_md(skill) -> str:
    out = [
        "# Citations index",
        "",
        "<!-- GENERATED from squat_standards.yaml by scripts/gen_skill_docs.py. Do not edit. -->",
        "",
        f"Source: *{skill.meta.document_title}* - {skill.meta.document_source}.",
        f"{skill.meta.page_offset_note}",
        "",
        "Every quote below is verbatim from the reference document and was checked against the "
        "PDF by hand. A fabricated citation would be worse here than no citation at all.",
        "",
        "## By criterion",
        "",
    ]
    for c in skill.criteria:
        out += [f"### {c.name}  \n`{c.id}` · {c.source.citation()}", ""]
        for label, q in (
            ("Standard", c.source.quote),
            ("Supporting", c.source.supporting_quote),
            ("Stated failure mode", c.source.failure_quote),
            ("Definition", c.source.midfoot_definition_quote),
        ):
            if q:
                out += [f"**{label}:**", "", f"> {' '.join(q.split())}", ""]
        if c.feedback_on_fail:
            pages = ", ".join(str(p) for p in c.feedback_on_fail.pages)
            out += [f"**Feedback drawn from ref p. {pages}:**", "",
                    f"> {' '.join(c.feedback_on_fail.text.split())}", ""]

    # Reverse index: page -> criteria
    pages: dict[int, list[str]] = {}
    for c in skill.criteria:
        for p in c.source.pages:
            pages.setdefault(p, []).append(c.name)
    out += ["## By reference page", "", "| Ref page | Criteria citing it |", "|---|---|"]
    for p in sorted(pages):
        out.append(f"| {p} | {', '.join(sorted(set(pages[p])))} |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    skill = load_skill()
    for name, text in (("coverage.md", coverage_md(skill)), ("CITATIONS.md", citations_md(skill))):
        path = ROOT / "skill" / name
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
