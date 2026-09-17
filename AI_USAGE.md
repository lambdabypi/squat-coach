# How I used AI on this build

Working notes, written as the build happened rather than reconstructed afterwards.

## What I delegated

- **Boilerplate with a known shape.** FastAPI wiring, Pydantic models, the ffprobe wrapper, React
  components, canvas drawing. Fast to generate, cheap to verify by reading.
- **Document → structured skill.** Turning the *Starting Strength* squat chapter into
  `skill/squat_standards.yaml` with per-criterion citations. I checked every quote and page number
  against the PDF by hand, because a fabricated citation is worse here than no citation.
- **Search and recall over the reference.** Locating which page states a given rule.

## What I inspected rather than trusted

- **Every threshold's provenance.** The document states almost no numbers. Each rule in the YAML is
  tagged `document_stated` or `engineering_tolerance`, and I went through them individually to
  confirm nothing got promoted from the second category to the first.
- **All geometry.** The model never measures anything. Depth, back angle, bar deviation and hip
  drive are computed in `vision/metrics.py`; the LLM receives those numbers as evidence and is only
  allowed to judge, explain and cite. If its structured output fails schema validation twice, the
  deterministic verdict ships without narration.
- **Landmark quality frame by frame,** not in aggregate. See below — this is where it mattered.

## The mistake I caught

**The barbell detector reported a 100% hit rate while being wrong most of the time.**

Block 1's smoke test ran MediaPipe pose and an OpenCV `HoughCircles` plate detector over five
frames of the common sample and printed:

```
pose 5/5 | plate 5/5
```

That is the kind of number it is very tempting to accept and move on from. It was on the happy
path, it was green, and the schedule was already tight.

I wrote the annotated frames to disk and looked at two of them instead. Frame 23's circle sat
neatly on the plate. **Frame 70's circle was enormous** — centred on the ceiling, enclosing most of
the upper half of the image. The printed radii told the same story once I read them as a series
rather than as five independent successes: `164, 306, 294, 306, 168`. A plate's apparent radius is
essentially constant for a fixed camera. Two clusters means the detector was locking onto two
different things, and the larger cluster was background structure — the rack, the rig, ceiling gaps.

So the real score was about 2/5, reported as 5/5. **The metric was measuring "did Hough return a
circle", not "did Hough return the plate".**

My first fix was wrong too, which is worth recording. I reasoned that since the true radius is
constant, I could sample the whole video, histogram the radii, and lock onto the mode. That
experiment came back:

```
top buckets: [(320, 73), (310, 52), (165, 42), (305, 41), (240, 39)]
locked band [274,370] -> 52/59 frames (88%)
bar x spread: min=49 max=725 std=231.8
```

88% "hit rate", and completely wrong. The spurious circles *outnumber* the real plate 73 to 42, so
the mode is the background, not the bar. The giveaway was the bar-x spread: a barbell path in a
correct squat is close to vertical, so x should barely move. A 232px standard deviation across a
1080px-wide frame is not a bar path, it's noise. **A second plausible-looking metric, wrong in the
same way as the first.**

The actual bug was in my search region. The smoke test constrained the search *vertically* to a
band around the shoulder, but left it unconstrained *horizontally* across all 1080 px — so every
piece of gym equipment in the frame was a candidate. The fix is to anchor the ROI to the pose in
both axes: a box around the shoulder landmark sized relative to the lifter's own torso length,
scored on darkness, proximity to the shoulder, and consistency with a running median radius, then
handed to a CSRT tracker with periodic re-detection.

**What I took from it.** Two things, one specific and one general. Specifically: a detector's hit
rate is worthless as a quality signal unless the "hit" is defined as the *right* detection —
count-based metrics on unvalidated detections launder failure into success. Generally: when a
result arrives green on a tight schedule, that is precisely when it deserves the look, because the
schedule is what makes you want to skip it.

This also changed the product, not just the code. It is why `Measurement.basis` distinguishes
`observed` from `estimated` throughout the report: when plate detection degrades — bumper-free
bars, cluttered racks, poor light — the system falls back to a shoulder-offset estimate and says so
on the finding, rather than presenting an inferred bar path with the same confidence as a tracked
one.

## The fallback path, verified by accident

Worth recording because it was not a drill. The first run with a real API key failed:

```
BadRequestError: 400 — This API key is not scoped to a workspace, so this request must
include the anthropic-workspace-id header with the ID of the workspace to use.
```

The application did what it was built to do. It caught the error, shipped the deterministic
verdicts and measurements unchanged, and wrote the exact error text into `agent_note` so the
report says why the wording is plainer than usual. Nothing was silently dropped, and no finding
changed.

That is the behaviour the design is for: the agent improves phrasing and writes the summary, so
losing it costs polish, not correctness. It also meant the degradation path was verified under a
genuine failure rather than a simulated one.

## Corrections still open

- Pose gives a hip *centre*, not the hip *crease* the document's depth standard refers to. This is a
  known systematic bias, documented in BUILD_NOTES rather than silently absorbed into a tolerance.
