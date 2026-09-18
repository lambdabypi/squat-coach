"""Repair UTF-8 text that was round-tripped through a single-byte codepage.

A PowerShell `Get-Content -Raw | Set-Content` pass re-encoded some source files, turning UTF-8
multi-byte sequences into mojibake. This reverses that: re-encode the text as cp1252 to recover
the original bytes, then decode them as UTF-8.
"""

from __future__ import annotations

import sys
from pathlib import Path


def repair(text: str) -> str:
    try:
        return text.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text  # not mojibake, or not recoverable this way


def main() -> int:
    changed = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        original = p.read_text(encoding="utf-8-sig")
        fixed = repair(original).lstrip("﻿")
        if fixed != original:
            p.write_text(fixed, encoding="utf-8", newline="\n")
            changed += 1
            print(f"repaired {p.name}")
        else:
            # Still normalise the BOM away.
            if original.startswith("﻿") or p.read_bytes()[:3] == b"\xef\xbb\xbf":
                p.write_text(original.lstrip("﻿"), encoding="utf-8", newline="\n")
                print(f"stripped BOM from {p.name}")
            else:
                print(f"no change  {p.name}")
    print(f"{changed} file(s) repaired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
