"""Prove that editing the skill YAML changes the assessment, with no application code touched.

This is the demo's central claim, so it gets a test rather than an assertion. It also confirms
the provenance guard rejects a tolerance that claims to come from the document.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.skill.loader import load_skill  # noqa: E402
from app.skill.rules import EVALUATORS  # noqa: E402

YAML = ROOT / "skill" / "squat_standards.yaml"
MEASURED = [59.161, 58.498]   # back angles actually measured on the common sample


def run(label: str) -> None:
    skill = load_skill(YAML)
    c = skill.by_id("back_angle")
    print(f"\n{label}: reference={c.rule.reference_value} tolerance={c.tolerance.value} "
          f"({c.tolerance.provenance.value})")
    for i, v in enumerate(MEASURED, 1):
        verdict, reason = EVALUATORS["back_angle"](v, c)
        print(f"  rep {i}  {v:.1f} deg -> {verdict}")


def main() -> int:
    original = YAML.read_text(encoding="utf-8")
    try:
        run("BEFORE (tolerance 15)")

        YAML.write_text(
            original.replace(
                "    tolerance:\n      value: 15\n      unit: degrees",
                "    tolerance:\n      value: 5\n      unit: degrees",
            ),
            encoding="utf-8", newline="\n",
        )
        run("AFTER  (tolerance 5)")

        # The provenance guard: a tolerance may never claim to be a document requirement.
        YAML.write_text(
            original.replace(
                "    tolerance:\n      value: 15\n      unit: degrees\n"
                "      provenance: engineering_tolerance",
                "    tolerance:\n      value: 15\n      unit: degrees\n"
                "      provenance: document_stated",
            ),
            encoding="utf-8", newline="\n",
        )
        try:
            load_skill(YAML)
            print("\nPROVENANCE GUARD: FAILED — a document_stated tolerance was accepted")
            return 1
        except Exception as exc:
            first = str(exc).strip().splitlines()
            msg = next((l for l in first if "tolerance" in l.lower()), first[-1])
            print(f"\nPROVENANCE GUARD: rejected as expected\n  {msg.strip()}")
    finally:
        YAML.write_text(original, encoding="utf-8", newline="\n")
        print("\nrestored the original skill file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
