"""Build the overall summary deterministically.

This was the language model's job until it kept making the same mistake: describing a depth
result that was too close to the *tolerance* to call as too close to call *from this camera
angle*. Those are different findings. One says the measurement was ambiguous; the other says the
evidence was never there. Conflating them is precisely the error this application exists to
avoid, and it appeared in the most-read paragraph of the report.

The summary is a roll-up of verdict counts and reasons. It does not need judgment, and it does
not need a model. Generating it here makes the distinction structural rather than something a
prompt has to keep asking for: the three kinds of "we could not say" are separate lists, built
from separate conditions, and cannot bleed into one another.

The agent still writes every per-finding explanation and every piece of coaching feedback. Only
the roll-up moved.
"""

from __future__ import annotations

from ..vision.quality import QualityReport
from .loader import Assessability, Skill
from .rules import FAILS, MEETS, UNKNOWN, Candidate


def _join(items: list[str], conj: str = "and") -> str:
    """Join a list readably.

    Several criterion names contain 'and' ('stance width and toe angle', 'rack height and
    unracking procedure'), so a plain comma-and join produces a run-on that the eye cannot
    segment. Lists of such names switch to semicolons.
    """
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    messy = any(" and " in i for i in items)
    if messy:
        return "; ".join(items)
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return ", ".join(items[:-1]) + f" {conj} {items[-1]}"


def _reps_phrase(n: int, total: int) -> str:
    if total <= 1:
        return ""
    if n == total:
        return "on both repetitions" if total == 2 else f"on all {total} repetitions"
    if n == 1:
        return "on one repetition"
    return f"on {n} of {total} repetitions"


def build_summary(
    skill: Skill,
    candidates: list[Candidate],
    n_reps: int,
    quality: QualityReport,
) -> str:
    """Two to four sentences, every clause traceable to a counted finding."""
    if not candidates or n_reps == 0:
        return "No repetition could be assessed in this video."

    order = [c.id for c in skill.criteria]          # skill file order is priority order

    def count(pred) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in candidates:
            if pred(c):
                out[c.criterion_id] = out.get(c.criterion_id, 0) + 1
        return out

    passed = count(lambda c: c.verdict == MEETS)
    failed = count(lambda c: c.verdict == FAILS)

    # The three distinct reasons a verdict can be withheld, kept apart by construction.
    structural = {                                   # the camera cannot see it, ever
        c.criterion_id for c in candidates
        if c.verdict == UNKNOWN
        and skill.by_id(c.criterion_id).assessable_from_side_view is Assessability.NONE
    }
    borderline = {                                   # measured, but inside our tolerance
        c.criterion_id for c in candidates
        if c.verdict == UNKNOWN
        and c.criterion_id not in structural
        and c.measurement is not None and c.measurement.available
    }
    unmeasured = {                                   # the evidence was not there in this clip
        c.criterion_id for c in candidates
        if c.verdict == UNKNOWN
        and c.criterion_id not in structural
        and (c.measurement is None or not c.measurement.available)
    }

    name = {c.id: c.name.lower() for c in skill.criteria}
    sentences: list[str] = []

    # 1. What held up. Only criteria clean on every repetition — a partial pass is not praise.
    clean = [cid for cid in order if passed.get(cid, 0) == n_reps]
    if clean:
        sentences.append(
            f"Your {_join([name[c] for c in clean])} met the standard "
            f"{_reps_phrase(n_reps, n_reps) or 'on this repetition'}.".replace("  ", " ")
        )

    # 2. The single most important thing to fix, by the skill's priority order.
    ranked = [cid for cid in order if cid in failed]
    if ranked:
        top = ranked[0]
        crit = skill.by_id(top)
        phrase = _reps_phrase(failed[top], n_reps)
        sentences.append(
            f"The main thing to fix is {name[top]}, which did not meet the standard"
            f"{' ' + phrase if phrase else ''} ({crit.source.citation()})."
        )
        rest = [name[c] for c in ranked[1:]]
        if rest:
            sentences.append(f"Also short: {_join(rest)}.")

    # 3. Ambiguous measurements — explicitly NOT a camera problem.
    if borderline:
        names = [name[c] for c in sorted(borderline, key=order.index)]
        verb = "landed" if len(names) == 1 else "landed"
        sentences.append(
            f"Your {_join(names)} {verb} inside our measurement tolerance, so it was too close "
            f"to call either way — that is a limit of the measurement, not of the camera angle."
        )

    # 4. Missing evidence in this particular clip — a recording problem, fixable by re-filming.
    #
    # A criterion can legitimately appear here *and* in the failure list when it failed on one
    # repetition and could not be measured on another. Saying so explicitly avoids a summary
    # that reads as if it contradicts itself.
    if unmeasured:
        both = unmeasured & set(failed)
        only = sorted(unmeasured - both, key=order.index)
        if only:
            sentences.append(
                f"We could not measure {_join([name[c] for c in only])} in this clip — the "
                f"evidence was not visible in the frames we needed."
            )
        for cid in sorted(both, key=order.index):
            n_unmeasured = sum(
                1 for c in candidates
                if c.criterion_id == cid and c.verdict == UNKNOWN
            )
            sentences.append(
                f"{name[cid].capitalize()} could not be measured "
                f"{_reps_phrase(n_unmeasured, n_reps) or 'on the other repetition'}, so that "
                f"verdict covers only part of the set."
            )

    # 5. Structurally invisible to a side view — no re-filming from this angle will help.
    if structural:
        sentences.append(
            f"A side view cannot judge {_join([name[c] for c in sorted(structural, key=order.index)])} "
            f"at all; those need a different camera angle."
        )

    degraded = [g for g in quality.gates if g.severity == "degraded"]
    if degraded and len(sentences) < 5:
        sentences.append(f"One caveat about the recording: {degraded[0].detail}")

    return " ".join(sentences)
