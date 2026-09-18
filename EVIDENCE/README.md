# Evidence

Three runs: the assignment's common sample, and two deliberately difficult recordings. All
produced with `scripts/run_cli.py --no-agent`, so every verdict here comes from the deterministic
rule engine and is reproducible without an API key.

Annotated stills are drawn from the same `overlay.json` the browser renders, so what is on disk is
what the product shows.

---

## 1. Common sample - `common-sample/`

`https://youtube.com/shorts/TRvg083BrXY` · VP9, 1080×1920 portrait, 30fps, 7.92s, 236 frames.

| | |
|---|---|
| Pose detected | 236 / 236 frames |
| Camera-facing side | LEFT (visibility margin 0.561) |
| Barbell plate detected | 189 / 236 frames (80%), median radius 169px |
| Repetitions | 2 - bottoms at 2.17s and 6.27s |
| Camera angle | side-on, view ratio 0.128 |
| Verdicts | 6 meets · 3 does not meet · 13 cannot assess |

Files: `report.json`, `overlay.json`, `rep1_top.jpg`, `rep1_bottom.jpg`, `rep2_top.jpg`,
`rep2_bottom.jpg`.

### What I verified, and how

**Landmark placement** - checked frame by frame in the annotated stills rather than trusting the
detection count. At `rep1_bottom` (t=2.17s) the hip, knee, ankle, heel and toe markers all sit on
the correct anatomy. Per-joint visibility was inspected individually, not averaged: the elbow
scores 0.38 mean and clears 0.6 in only 3 of 236 frames, because the arms are behind the torso and
the plate in a side view. It is not used by any criterion. Knee visibility is 0.84 and drops below
threshold in 20 frames, all near lockout where the two legs overlap - which is the far-leg
occlusion the near-side selection exists to handle.

**Depth is genuinely borderline, and the report says so.** At both bottoms the hip and knee
landmarks sit at nearly identical height - +0.019 and -0.010 shin-lengths. That is inside the
0.03 measurement tolerance, so both repetitions return `cannot_assess` rather than a verdict. The
stills confirm this is real and not a tracking failure: the athlete is at roughly parallel. Given
that the pose model reports a hip *joint centre* while the document's standard is the hip *crease*
(Fig 2-1, ref p.2) - a bias of a few centimetres in the "too high" direction - a confident call
either way would not be defensible here.

**Bar path** - the decisive check was the horizontal spread, because a correct squat's bar path is
near-vertical. Observed bar x spans 584-674px with a 29.4px standard deviation, on a 1080px-wide
frame: 0.114 shin-lengths. An earlier, broken version of the detector produced a 231.8px standard
deviation while reporting a higher hit rate - see `../AI_USAGE.md`. Vertical travel is 572px, the
squat itself. 44 frames were rejected by the radius-consistency check as background structure.
Residual horizontal jitter of roughly ±30px is visible in the annotated trail and is honest noise,
not drift.

**Source grounding** - every finding carries its reference pages and the verbatim quote behind the
criterion, surfaced in the UI. Provenance is separated: the depth *rule* is `document_stated` (the
document defines it geometrically), while the ±0.03 shin-length band is `engineering_tolerance` and
is labelled as ours in the report and in the interface. No numeric threshold in this run is
attributed to the document that the document does not state.

**Final feedback** - failures quote the document's own coaching language. The bar-path failure
(0.265 and 0.238 shin-lengths from the midfoot, beyond our 0.15 allowance) draws on ref p.11-12 on
the cost of an out-of-balance bar. The rep-1 hip-drive failure (ratio 0.696 - shoulders rising
faster than hips) draws on ref p.24, "a chain hooked to your hips, pulling you straight up out of
the bottom".

**Three criteria abstain structurally** - knees-out, stance and rack height - with the camera angle
that would be needed stated for each. These are three of the document's own eight headline faults,
including the one it emphasises most.

---

## 2. Difficult recording A - `hard-sample/degraded/`

The common sample deliberately degraded with ffmpeg: bottom 38% cropped away (feet removed),
brightness -0.22, contrast 0.72, downscaled to 608×670, re-encoded at CRF 30.

**Result: correctly refused.**

```
[warn] sagittal_view    The camera angle could not be checked reliably because the athlete
                        was detected in too few frames. Fix the lighting and framing first.
[FAIL] person_detected  A person was detected in only 21% of frames.
[ok  ] rep_detected     3 repetition(s) identified.
[FAIL] feet_in_frame    The feet leave the frame in 79% of frames.
[FAIL] bar_tracked      The barbell plate was detected in only 0% of frames.
```

No findings were produced. The report sets `blocked: true` and explains why in words.

Worth noting what it got wrong first: the camera-angle gate originally asserted *"this does not
appear to be a side view"* - a confident and false diagnosis, since this is a crop of a genuine
side view. The angle test is computed from landmark positions, so it is meaningless when the
person is barely detected. It now defers to the detection gate. A gate that exists to prevent
overconfident conclusions was itself drawing one.

Note also that rep segmentation still found "3 repetitions" in a 2-repetition clip. Hip-height
peaks from unstable landmarks produced a phantom. It does not reach the user, because the blocking
gates fire first - but it is a real limitation of the segmenter under bad tracking.

---

## 3. Difficult recording B - `hard-sample/frontview/`

A front-facing squat clip from YouTube, trimmed to 20s at 1280×720. This is the useful complement
to A: the footage is perfectly clear, and simply shot from the wrong plane.

**Result: correctly refused, for the right reason.**

```
[FAIL] sagittal_view    This does not appear to be a side view. The reference document defines
                        squat depth on the profile view, so no criterion can be assessed from
                        this angle. Re-record with the camera directly to one side.
[ok  ] person_detected  A person was detected in 87% of frames.
[ok  ] rep_detected     3 repetition(s) identified.
[FAIL] bar_tracked      The barbell plate was detected in only 3% of frames.
```

This is the evidence that the camera-angle gate discriminates rather than firing on anything
difficult: detection is high, repetitions are found, and it still refuses - on angle alone. Plate
detection at 3% is the expected corollary, since a front view shows the plate edge-on rather than
as a circle.

The full untrimmed download was also rejected earlier, at the probe stage, with
`The video is 435s. Please trim it to 60s or less` - the cheap gate doing its job before any
compute was spent.

---

## Reproducing

```bash
python scripts/fetch_sample.py
python scripts/run_cli.py EVIDENCE/common-sample/common_sample.mp4 \
       --out EVIDENCE/common-sample --no-agent
python scripts/export_frames.py EVIDENCE/common-sample/common_sample.mp4 \
       EVIDENCE/common-sample
```

Source videos are gitignored; the reports, overlays and annotated stills are committed.
