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
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_venv_interpreter() -> None:
    """Re-run under the project venv if the dependencies are not on this interpreter.

    `python scripts/deploy_hf.py` picks up whatever `python` means on PATH, which on a machine
    with a system Python is not the venv this project installed into. The failure is a bare
    ModuleNotFoundError that says nothing about which interpreter to use, so fix it here instead
    of asking the reader to know.
    """
    try:
        import huggingface_hub  # noqa: F401
        return
    except ImportError:
        pass

    venv_python = ROOT / "backend" / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if not venv_python.exists():
        print("huggingface_hub is not installed and no project venv was found at")
        print(f"  {venv_python}")
        print("\nCreate it first (see README Quick start), then:")
        print(f"  {venv_python} -m pip install huggingface_hub")
        raise SystemExit(1)

    if Path(sys.executable).resolve() == venv_python.resolve():
        print("Running under the project venv, but huggingface_hub is missing. Install it:")
        print(f"  {venv_python} -m pip install huggingface_hub")
        raise SystemExit(1)

    # Flush before handing over, or this line lands after the child's output.
    print(f"Switching to the project interpreter: {venv_python}\n", flush=True)
    raise SystemExit(subprocess.call([str(venv_python), __file__, *sys.argv[1:]]))


_ensure_venv_interpreter()

from huggingface_hub import HfApi, whoami  # noqa: E402

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

    token = args.token or None
    try:
        user = whoami(token=token)["name"]
    except Exception:
        # The `hf` CLI installs into whichever environment huggingface_hub went into, which for
        # this project is the backend venv rather than the system PATH. Spell that out instead
        # of printing a command the shell will not find.
        venv_hf = ROOT / "backend" / ".venv" / "Scripts" / "hf.exe"
        cli = venv_hf if venv_hf.exists() else Path("hf")
        print("\nNot authenticated with Hugging Face. Pick either:")
        print(f"\n  1. Log in once:\n       {cli} auth login")
        print("\n  2. Or pass a token directly:")
        print("       python scripts/deploy_hf.py --token hf_xxx")
        print("\n  3. Or set it for the session:")
        print("       $env:HF_TOKEN = 'hf_xxx'      # PowerShell")
        print("       export HF_TOKEN=hf_xxx        # bash")
        print("\nCreate a token at https://huggingface.co/settings/tokens")
        print("It needs WRITE permission; a read token cannot create a Space.")
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
