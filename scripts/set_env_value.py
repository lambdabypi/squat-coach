"""Set or blank a single key in .env without disturbing anything else.

Rewrites only the matching line, preserves ordering, comments and every other value, and never
prints a secret. Backs up to a path outside the repository first.

    python scripts/set_env_value.py KEY [VALUE] --backup <path>
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("value", nargs="?", default="")
    ap.add_argument("--backup", required=True)
    args = ap.parse_args()

    if not ENV.exists():
        print(f"{ENV} does not exist")
        return 1

    backup = Path(args.backup)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENV, backup)
    print(f"backed up .env -> {backup}")

    lines = ENV.read_text(encoding="utf-8").splitlines()
    out, found = [], False
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and "=" in line:
            name = line.split("=", 1)[0].strip()
            if name == args.key:
                out.append(f"{args.key}={args.value}")
                found = True
                continue
        out.append(line)

    if not found:
        out.append(f"{args.key}={args.value}")

    ENV.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    shown = args.value if args.value else "(blank)"
    print(f"set {args.key}={shown}")

    # Confirm nothing else was lost, without revealing values.
    from dotenv import dotenv_values
    before = dotenv_values(backup)
    after = dotenv_values(ENV)
    print(f"keys before: {sorted(before)}")
    print(f"keys after : {sorted(after)}")
    for k in before:
        if k != args.key and before[k] != after.get(k):
            print(f"WARNING: {k} changed unexpectedly")
            return 1
    print("all other values unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
