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

    client = Anthropic(
        default_headers={"anthropic-workspace-id": workspace} if workspace else None
    )
    try:
        r = client.messages.create(
            model=MODEL,
            max_tokens=4,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"\nFAILED: {type(exc).__name__}")
        print(f"  {msg[:400]}")
        if "workspace" in msg.lower():
            print("\n  -> This key is organisation-scoped. Either add")
            print("     ANTHROPIC_WORKSPACE_ID=<id> to squat-coach/.env,")
            print("     or use a key created inside a workspace.")
        return 1

    text = "".join(b.text for b in r.content if b.type == "text").strip()
    print(f"\nOK: {MODEL} replied {text!r}")
    print(f"tokens: in={r.usage.input_tokens} out={r.usage.output_tokens}")
    print("The agent stage will narrate assessments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
