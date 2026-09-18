"""Does the cached skill block actually cache on the configured model?

BUILD_NOTES claims the skill block is cached across videos, so subsequent runs are cheaper.
The first Haiku run reported cache_write_tokens = 0, which would make that claim false. This
sends the same prefix twice and reports what the API says, rather than what we assume.

Costs a few cents.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from anthropic import Anthropic  # noqa: E402

from app.agent.assess import MODEL  # noqa: E402
from app.agent.prompts import skill_block  # noqa: E402
from app.skill.loader import load_skill  # noqa: E402


def main() -> int:
    skill = load_skill()
    block = skill_block(skill)
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = Anthropic(
        default_headers={"anthropic-workspace-id": workspace} if workspace else None
    )

    counted = client.messages.count_tokens(
        model=MODEL,
        messages=[{"role": "user", "content": [{"type": "text", "text": block}]}],
    )
    print(f"model            : {MODEL}")
    print(f"skill block size : {counted.input_tokens} tokens\n")

    for attempt in (1, 2):
        r = client.messages.create(
            model=MODEL,
            max_tokens=8,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": block, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "Reply with the single word: ok"},
                ],
            }],
        )
        u = r.usage
        print(f"call {attempt}: input={u.input_tokens} "
              f"cache_write={getattr(u, 'cache_creation_input_tokens', 0) or 0} "
              f"cache_read={getattr(u, 'cache_read_input_tokens', 0) or 0} "
              f"output={u.output_tokens}")

    print("\nIf cache_write is 0 on call 1 and cache_read is 0 on call 2, the prefix is below")
    print("this model's minimum cacheable length and the caching claim does not hold for it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
