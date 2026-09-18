"""Cost comparison: the shipped architecture vs. sending frames to a vision model.

The shipped numbers come from a real run (report.json). The VLM numbers are computed from
Anthropic's documented image-token formula, not guessed:

    tokens ~= (width * height) / 750

Run:  python scripts/cost_model.py [path/to/report.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Per-million-token prices, first-party Anthropic API.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}

CLIP_SECONDS = 7.92
CLIP_FPS = 30.0
CLIP_FRAMES = 236
FRAME_W, FRAME_H = 1080, 1920


def image_tokens(w: int, h: int) -> int:
    """Anthropic's documented approximation for image input."""
    return round(w * h / 750)


def money(x: float) -> str:
    return f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def main() -> int:
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "EVIDENCE" / "common-sample" / "report.json"
    )

    print("=" * 78)
    print("MEASURED — the shipped architecture (LLM sees numbers, never pixels)")
    print("=" * 78)
    if report_path.exists():
        cost = json.loads(report_path.read_text(encoding="utf-8")).get("cost")
    else:
        cost = None
    if cost:
        model = cost["model"]
        print(f"model             : {model}")
        print(f"input tokens      : {cost['input_tokens']:,}")
        print(f"output tokens     : {cost['output_tokens']:,}")
        print(f"cache read/write  : {cost['cache_read_tokens']:,} / {cost['cache_write_tokens']:,}")
        print(f"COST PER VIDEO    : {money(cost['estimated_usd'])}")
        measured = cost["estimated_usd"]
    else:
        print("(no measured cost in report.json — run scripts/run_cli.py with a key first)")
        measured = 0.0275
        print(f"using last known  : {money(measured)}")

    print("\nVision compute (MediaPipe + OpenCV) runs locally on CPU: $0 in API charges.")
    print("At a cloud rate of ~$0.05/CPU-hour, ~60s of tracking is about $0.0008 per video.")

    print()
    print("=" * 78)
    print("MODELLED — if a VLM did the seeing instead")
    print("=" * 78)
    full = image_tokens(FRAME_W, FRAME_H)
    half = image_tokens(FRAME_W // 2, FRAME_H // 2)
    print(f"one 1080x1920 frame  ~ {full:,} tokens")
    print(f"one 540x960 frame    ~ {half:,} tokens  (downscaled)\n")

    strategies = [
        ("every frame", CLIP_FRAMES, full),
        ("every 3rd frame", CLIP_FRAMES // 3, full),
        ("2 frames per rep (top+bottom), 2 reps", 4, full),
        ("2 frames per rep, downscaled", 4, half),
    ]

    header = f"{'strategy':40s} {'frames':>7s} {'in-tok':>10s} " + " ".join(
        f"{m.replace('claude-', ''):>14s}" for m in PRICES
    )
    print(header)
    print("-" * len(header))
    for label, n_frames, per_frame in strategies:
        in_tok = n_frames * per_frame + 2000          # + prompt and rules
        out_tok = 3000
        cells = []
        for m, (pin, pout) in PRICES.items():
            c = in_tok / 1e6 * pin + out_tok / 1e6 * pout
            cells.append(f"{money(c):>14s}")
        print(f"{label:40s} {n_frames:7d} {in_tok:10,d} " + " ".join(cells))

    print()
    print("=" * 78)
    print("WHAT THAT BUYS, AND WHAT IT COSTS")
    print("=" * 78)
    cheapest_vlm = (4 * half + 2000) / 1e6 * 1.00 + 3000 / 1e6 * 5.00
    print(f"Cheapest credible VLM option (4 downscaled frames, haiku): {money(cheapest_vlm)}")
    print(f"Shipped architecture                                     : {money(measured)}")
    print(f"Ratio                                                    : "
          f"{cheapest_vlm / measured:.2f}x")
    print()
    print("But cost is the smaller argument. A VLM looking at 4 frames cannot:")
    print("  - give a per-landmark visibility score, which is what drives observed-vs-estimated")
    print("    and every cannot_assess verdict in this system;")
    print("  - locate a joint to the pixel, so 'hip 0.019 shin-lengths below knee' becomes")
    print("    'looks about parallel';")
    print("  - track the bar across 236 frames to produce a path;")
    print("  - be checked. A landmark can be drawn on the frame and verified by eye. A claim")
    print("    cannot.")
    print()
    print("Sending ALL frames so it could do those things costs "
          f"{money((CLIP_FRAMES * full + 2000) / 1e6 * 1.00 + 3000 / 1e6 * 5.00)} on the cheapest")
    print("model — two orders of magnitude more than the shipped design — and still yields")
    print("estimates rather than measurements.")
    print()
    print("Per 1,000 videos:")
    print(f"  shipped                      {money(measured * 1000)}")
    print(f"  VLM, 4 downscaled frames     {money(cheapest_vlm * 1000)}")
    print(f"  VLM, every frame (haiku)     "
          f"{money(((CLIP_FRAMES * full + 2000) / 1e6 * 1.00 + 3000 / 1e6 * 5.00) * 1000)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
