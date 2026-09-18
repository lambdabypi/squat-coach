"""Replace em dashes, en dashes and curly quotes with plain ASCII across the repository.

    python scripts/strip_emdashes.py            # report only
    python scripts/strip_emdashes.py --write    # apply

Substitution only, never whitespace. An earlier version also tidied spacing around the
substituted dashes, which collapsed every two-space-indented YAML and Markdown list item by one
space, broke the skill file and stopped the backend from booting. It rewrote its own source in
the process. Cosmetic cleanup is not worth that blast radius in indentation-sensitive files.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUFFIXES = {".md", ".py", ".ts", ".tsx", ".css", ".yaml", ".yml", ".json", ".txt"}
SKIP_DIRS = {".git", "node_modules", ".venv", ".next", "models", "storage", "__pycache__"}

# Keyed by codepoint so this file contains no such characters itself.
REPLACEMENTS = {
    0x2014: "-",      # em dash
    0x2013: "-",      # en dash
    0x2212: "-",      # minus sign
    0x2018: "'",      # left single quote
    0x2019: "'",      # right single quote
    0x201C: '"',      # left double quote
    0x201D: '"',      # right double quote
    0x2026: "...",    # ellipsis
    0x00A0: " ",      # non-breaking space
}

TABLE = {k: v for k, v in REPLACEMENTS.items()}


def clean(text: str) -> str:
    return text.translate(TABLE)


def count_hits(text: str) -> int:
    return sum(text.count(chr(cp)) for cp in REPLACEMENTS)


def main() -> int:
    write = "--write" in sys.argv
    touched = 0
    total = 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = count_hits(original)
        if not hits:
            continue
        total += hits
        touched += 1
        print(f"{hits:5d}  {path.relative_to(ROOT)}")
        if write:
            path.write_text(clean(original), encoding="utf-8", newline="\n")

    print(f"\n{total} character(s) across {touched} file(s)")
    if not write:
        print("dry run - pass --write to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
