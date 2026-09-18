"""Deploy the backend to a Hugging Face Docker Space.

    hf auth login                      # once, or set HF_TOKEN
    python scripts/deploy_hf.py --name squat-coach-api

Uploads only what the container needs: the Dockerfile, the backend package, the skill, and the
requirements. Not the frontend, not EVIDENCE, not the venv.

The Space README needs YAML frontmatter that Hugging Face reads for configuration. It is written
here rather than committed to the repository root, so the GitHub README stays a README instead of
carrying a config block for a different platform.

Deliberately does NOT upload ANTHROPIC_API_KEY. A public Space with no authentication means
anyone who finds it can spend your credit. Without a key the deterministic rule engine produces
every verdict, measurement and citation on its own; only the narration wording is plainer. If you
want the agent on a live demo, set the secret in the Space settings yourself and take it down
afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import HfApi, whoami

ROOT = Path(__file__).resolve().parents[1]

SPACE_README = """\
---
title: {title}
emoji: 🏋️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# {title}

Backend API for Squat Coach: side-view barbell squat analysis assessed against a
document-derived agent skill.

Source: https://github.com/{gh_user}/squat-coach

## Endpoints

- `GET  /health` - service status and whether the agent is configured
- `GET  /requirements` - supported formats, limits and recording guidance
- `GET  /skill` - the document-derived assessment standard
- `POST /videos` - upload a side-view squat clip
- `GET  /jobs/{{id}}` - progress
- `GET  /jobs/{{id}}/report` - findings
- `GET  /jobs/{{id}}/overlay` - per-frame landmark and angle data

## Notes

Running without `ANTHROPIC_API_KEY`, so assessments come from the deterministic rule engine.
Every verdict, measurement, citation and uncertainty note is identical to the full build; only
the narration wording is plainer.

Jobs are held in memory, so a restart or a scale-to-zero loses in-flight work. Free Spaces sleep
when idle and take a moment to wake.
"""

# Everything the container needs, and nothing else.
INCLUDE_FILES = ["Dockerfile", ".dockerignore", "backend/requirements.txt"]
INCLUDE_DIRS = ["backend/app", "skill"]
SKIP_PARTS = {"__pycache__", ".venv", "node_modules", ".next", "storage", "models"}


def gather() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.exists():
            out.append((p, rel))
    for rel in INCLUDE_DIRS:
        for p in sorted((ROOT / rel).rglob("*")):
            if not p.is_file():
                continue
            if any(part in SKIP_PARTS for part in p.parts):
                continue
            if p.suffix in {".pyc", ".task"}:
                continue
            out.append((p, p.relative_to(ROOT).as_posix()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="squat-coach-api")
    ap.add_argument("--gh-user", default="lambdabypi")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = gather()
    total = sum(p.stat().st_size for p, _ in files)
    print(f"{len(files)} files, {total / 1e6:.1f} MB")
    for _, rel in files[:6]:
        print(f"  {rel}")
    if len(files) > 6:
        print(f"  ... and {len(files) - 6} more")

    if args.dry_run:
        print("\ndry run, nothing uploaded")
        return 0

    try:
        user = whoami()["name"]
    except Exception:
        print("\nNot authenticated. Run `hf auth login`, or set HF_TOKEN, then retry.")
        return 1

    repo_id = f"{user}/{args.name}"
    print(f"\ndeploying to https://huggingface.co/spaces/{repo_id}")

    api = HfApi()
    api.create_repo(
        repo_id=repo_id, repo_type="space", space_sdk="docker",
        private=args.private, exist_ok=True,
    )

    readme = ROOT / ".hf_space_README.md"
    readme.write_text(
        SPACE_README.format(title=args.name, gh_user=args.gh_user),
        encoding="utf-8", newline="\n",
    )
    try:
        api.upload_file(
            path_or_fileobj=str(readme), path_in_repo="README.md",
            repo_id=repo_id, repo_type="space",
        )
        for path, rel in files:
            api.upload_file(
                path_or_fileobj=str(path), path_in_repo=rel,
                repo_id=repo_id, repo_type="space",
            )
            print(f"  uploaded {rel}")
    finally:
        readme.unlink(missing_ok=True)

    url = f"https://huggingface.co/spaces/{repo_id}"
    print(f"\ndone: {url}")
    print(f"API base for the frontend: https://{user}-{args.name}.hf.space".lower())
    print("\nThe Space builds the Dockerfile now; first build takes a few minutes.")
    print("Then set NEXT_PUBLIC_API_URL on Vercel to the API base above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
