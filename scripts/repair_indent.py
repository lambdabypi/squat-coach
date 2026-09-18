"""Repair indentation collapsed by the earlier strip_emdashes bug.

That script's whitespace "tidying" turned every `  - item` into ` - item`, and `    - item`
into `   - item`. This restores the original leading whitespace by comparing each file against
git HEAD: for any line whose visible content is unchanged apart from the dash and quote
substitutions, HEAD's indentation wins. Lines written since the commit are left alone.

    python scripts/repair_indent.py [--write]
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strip_emdashes import SKIP_DIRS, SUFFIXES, clean  # noqa: E402


def head_text(rel: str) -> str | None:
    r = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.stdout if r.returncode == 0 else None


def leading(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


def main() -> int:
    write = "--write" in sys.argv
    fixed_files = 0
    fixed_lines = 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        rel = path.relative_to(ROOT).as_posix()
        head = head_text(rel)
        if head is None:
            continue

        # content -> set of indents seen in HEAD for that content
        indents: dict[str, set[str]] = defaultdict(set)
        for line in head.splitlines():
            if line.strip():
                indents[clean(line).strip()].add(leading(line))

        current = path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        changed = 0
        for line in current:
            body = line.strip()
            cands = indents.get(body)
            if body and cands and len(cands) == 1:
                want = next(iter(cands))
                if leading(line) != want:
                    line = want + body
                    changed += 1
            out.append(line)

        if changed:
            fixed_files += 1
            fixed_lines += changed
            print(f"{changed:5d}  {rel}")
            if write:
                path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")

    print(f"\n{fixed_lines} line(s) across {fixed_files} file(s)")
    if not write:
        print("dry run - pass --write to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
