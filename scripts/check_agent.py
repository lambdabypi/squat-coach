"""Cheapest possible check that the agent stage can actually reach the API.

Run this before a demo. It costs a fraction of a cent and tells you in one line whether the
assessment will be narrated by the agent or fall back to the rule engine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app.agent.assess import MODEL  # noqa: E402


def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY")
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    print(f"ANTHROPIC_API_KEY      : {'set' if key else 'MISSING'}")
    print(f"ANTHROPIC_WORKSPACE_ID : {workspace or '(not set)'}")
    if not key:
        print("\nNo key. The pipeline will run deterministic-only.")
        return 1

    from anthropic import Anthropic

    def attempt(label: str, ws: str | None) -> tuple[bool, str]:
        client = Anthropic(
            default_headers={"anthropic-workspace-id": ws} if ws else None
        )
        try:
            r = client.messages.create(
                model=MODEL,
                max_tokens=4,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:28s} FAILED  {type(exc).__name__}: {str(exc)[:200]}")
            return False, str(exc)
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        print(f"  {label:28s} OK      replied {text!r} "
              f"(in={r.usage.input_tokens} out={r.usage.output_tokens})")
        return True, ""

    print("Trying both header configurations:\n")
    with_ok, with_err = (attempt("with workspace header", workspace)
                         if workspace else (False, "no workspace configured"))
    without_ok, without_err = attempt("without workspace header", None)

    print()
    if without_ok and not workspace:
        print(f"DIAGNOSIS: working. Model {MODEL} reachable; the key is workspace-scoped and")
        print("           needs no workspace header.")
        return 0
    if without_ok:
        print("DIAGNOSIS: the key works WITHOUT a workspace header, but a workspace id is set.")
        print("  -> Blank ANTHROPIC_WORKSPACE_ID in squat-coach/.env.")
        print("     This key is workspace-scoped already; sending the header names a second")
        print("     workspace and fails with a 404.")
        return 1
    if with_ok:
        print(f"DIAGNOSIS: working. Model {MODEL} reachable with the configured workspace.")
        return 0

    print("DIAGNOSIS: neither configuration works.")
    if "not_found" in with_err or "not found" in with_err.lower():
        print("  -> The configured workspace id does not exist for THIS key's organisation.")
        print("     Either the key was replaced with one from a different org, or the")
        print("     workspace was deleted. Check the Anthropic Console: Settings -> Workspaces,")
        print("     and copy the id from the URL of the workspace the key belongs to.")
    elif "scoped to a workspace" in without_err:
        print("  -> The key is organisation-scoped and needs a VALID workspace id.")
    else:
        print("  -> See the errors above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
