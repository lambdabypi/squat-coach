"""Does the same video, analysed again, give the same answer?

A coaching verdict that moves between two uploads of one file is not a measurement, it is a coin
toss with units. This runs the same clip through the pipeline several times and compares every
verdict and every measurement exactly.

Three sources of variation are worth separating, because they have different answers:

  1. The measurement core - pose, smoothing, repetition segmentation, metrics, rules. Should be
     bit-identical: same file, same frames, same arithmetic, no sampling anywhere.
  2. The language model narration, when an API key is configured. The Anthropic default
     temperature is 1.0 and nothing in this codebase overrides it, so the *wording* varies by
     design even though the verdicts it narrates do not. Run with --agent to see it.
  3. The browser-tracking path, which this script cannot reach. It decodes by seeking per frame
     and may run the WASM build on a GPU delegate, neither of which this process exercises.

    python scripts/check_determinism.py <video> [runs] [--agent]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import analyse  # noqa: E402


def fingerprint(report: dict) -> tuple[dict, dict, dict]:
    verdicts, values, confidence = {}, {}, {}
    for f in report["findings"]:
        k = f"rep{f['rep_index']}.{f['criterion_id']}"
        verdicts[k] = f["verdict"]
        confidence[k] = f["confidence"]
        m = f.get("measurement") or {}
        values[k] = m.get("value") if isinstance(m, dict) else None
    return verdicts, values, confidence


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--agent"]
    use_agent = "--agent" in sys.argv
    video = Path(args[0])
    runs = int(args[1]) if len(args) > 1 else 3

    print(f"{video.name}, {runs} runs, agent={'on' if use_agent else 'off'}\n")

    base = None
    summaries: list[str] = []
    problems = 0
    for i in range(runs):
        out = analyse(video, use_agent=use_agent)
        rep = out["report"]
        fp = fingerprint(rep)
        summaries.append(rep.get("summary") or "")

        reps = len(rep.get("reps", []))
        counts: dict[str, int] = {}
        for v in fp[0].values():
            counts[v] = counts.get(v, 0) + 1
        print(f"run {i + 1}: reps={reps}  {counts}")

        if base is None:
            base = fp
            continue

        for label, idx in (("verdict", 0), ("measurement", 1), ("confidence", 2)):
            a, b = base[idx], fp[idx]
            diff = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
            if diff:
                problems += 1
                print(f"  {label.upper()} DRIFT on {len(diff)} item(s):")
                for k in diff[:8]:
                    print(f"    {k:34s} {a.get(k)!r} -> {b.get(k)!r}")

    # The narration is a separate question from the verdicts.
    if use_agent:
        unique = len(set(summaries))
        print(f"\nnarration: {unique} distinct summary text(s) across {runs} runs")
        if unique > 1:
            print("  The wording varies. That is the sampling temperature, not the assessment:")
            print("  the verdicts above are what the narration describes, and they are compared")
            print("  separately. Worth pinning temperature=0 if identical prose matters.")

    print("\n" + "=" * 72)
    if problems:
        print(f"{problems} drift(s) found: the same file produced different answers.")
        return 1
    print(f"Identical across {runs} runs: every verdict, measurement and confidence level.")
    print("Re-uploading the same file therefore cannot change the result, only spend the compute")
    print("again. This covers the server path only; the browser path is not exercised here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
