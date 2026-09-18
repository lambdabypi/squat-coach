"""Prove the one-way confidence guard.

The agent may move a verdict toward `cannot_assess` and never away from it. On a clean run the
guard never fires, which means it would be untested exactly when it matters. This drives the
merge logic directly with a fabricated agent response.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.assess import merge_verdict  # noqa: E402
from app.skill.rules import FAILS, MEETS, UNKNOWN  # noqa: E402

CASES = [
    # (rule engine said, agent proposed, expected kept, expected override, why)
    (UNKNOWN, MEETS, UNKNOWN, True, "tried to upgrade an abstention to a pass - discarded"),
    (UNKNOWN, FAILS, UNKNOWN, True, "tried to upgrade an abstention to a failure - discarded"),
    (MEETS, FAILS, MEETS, True, "tried to flip a pass to a failure - discarded"),
    (FAILS, MEETS, FAILS, True, "tried to flip a failure to a pass - discarded"),
    (MEETS, UNKNOWN, UNKNOWN, False, "abstained from a pass - allowed"),
    (FAILS, UNKNOWN, UNKNOWN, False, "abstained from a failure - allowed"),
    (MEETS, MEETS, MEETS, False, "agreement"),
    (FAILS, FAILS, FAILS, False, "agreement"),
    (UNKNOWN, UNKNOWN, UNKNOWN, False, "agreement"),
]


def main() -> int:
    failures = 0
    for rule_v, agent_v, expected, expect_override, why in CASES:
        got, overridden = merge_verdict(rule_v, agent_v)
        ok = got == expected and overridden == expect_override
        failures += not ok
        mark = "ok  " if ok else "FAIL"
        flag = " [overridden]" if overridden else ""
        print(f"[{mark}] rules={rule_v:24s} agent={agent_v:24s} -> {got:24s}{flag}  ({why})")

    print()
    if failures:
        print(f"{failures} case(s) FAILED - the guard does not hold")
        return 1
    print("All cases hold: the agent may only abstain. It can never upgrade an abstention into a")
    print("verdict, nor flip a pass to a failure or back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
