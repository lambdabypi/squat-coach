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
- **Landmark quality frame by frame,** not in aggregate. See below - this is where it mattered.
- **Whether the verdicts survive the real browser.** The measurement layer was verified entirely
  through Python, including a test that replays browser-shaped input through the client endpoint.
  That test passes and is not sufficient: it uses native MediaPipe, and production runs the same
  model compiled to WASM. Driving actual Chromium found a verdict the two backends disagreed on.
- **Whether the corrected pose is achievable, not just valid.** Geometric validity and physical
  possibility are different questions, and only the first had a test.

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
neatly on the plate. **Frame 70's circle was enormous** - centred on the ceiling, enclosing most of
the upper half of the image. The printed radii told the same story once I read them as a series
rather than as five independent successes: `164, 306, 294, 306, 168`. A plate's apparent radius is
essentially constant for a fixed camera. Two clusters means the detector was locking onto two
different things, and the larger cluster was background structure - the rack, the rig, ceiling gaps.

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
band around the shoulder, but left it unconstrained *horizontally* across all 1080 px - so every
piece of gym equipment in the frame was a candidate. The fix is to anchor the ROI to the pose in
both axes: a box around the shoulder landmark sized relative to the lifter's own torso length,
scored on darkness, proximity to the shoulder, and consistency with a running median radius, then
handed to a CSRT tracker with periodic re-detection.

**What I took from it.** Two things, one specific and one general. Specifically: a detector's hit
rate is worthless as a quality signal unless the "hit" is defined as the *right* detection -
count-based metrics on unvalidated detections launder failure into success. Generally: when a
result arrives green on a tight schedule, that is precisely when it deserves the look, because the
schedule is what makes you want to skip it.

This also changed the product, not just the code. It is why `Measurement.basis` distinguishes
`observed` from `estimated` throughout the report: when plate detection degrades - bumper-free
bars, cluttered racks, poor light - the system falls back to a shoulder-offset estimate and says so
on the finding, rather than presenting an inferred bar path with the same confidence as a tracked
one.

## The fallback path, verified by accident

Worth recording because it was not a drill. The first run with a real API key failed:

```
BadRequestError: 400 - This API key is not scoped to a workspace, so this request must
include the anthropic-workspace-id header with the ID of the workspace to use.
```

The application did what it was built to do. It caught the error, shipped the deterministic
verdicts and measurements unchanged, and wrote the exact error text into `agent_note` so the
report says why the wording is plainer than usual. Nothing was silently dropped, and no finding
changed.

That is the behaviour the design is for: the agent improves phrasing and writes the summary, so
losing it costs polish, not correctness. It also meant the degradation path was verified under a
genuine failure rather than a simulated one.

## A second mistake, in the deployment

Worth adding because it is the same shape as the first: an optimisation that looked like it
worked, reported success, and was wrong.

Building the deployment container, I swapped `opencv-contrib-python` for the smaller
`opencv-python-headless` to save about 75 MB, reasoning that this project uses only base OpenCV
calls. The container built, passed its health check, and analysed the common sample end to end.

Then the verdict counts came back **12 / 6 / 4** where the verified host build gives
**13 / 6 / 3**. One finding had silently changed: back angle flipped from `meets_standard` to
`does_not_meet_standard` on a repetition.

The cause took two attempts to find.

**First attempt.** My `sed` had replaced the package name *and dropped the version pin*, so pip
resolved OpenCV **5.0** against the **4.12** everything was verified on. A major version of the
library that both decodes the video and runs `HoughCircles` had changed underneath the
measurements. I pinned the headless package and rebuilt.

**Still 5.0.** The real reason is that **mediapipe 1.0.1 declares `opencv-contrib-python` as its
own dependency, unpinned**. pip honoured my headless pin *and* pulled contrib 5.0.0.93 to satisfy
mediapipe. Both packages install into the same `cv2` namespace, contrib shadowed headless, and
the image ran OpenCV 5 while its own requirements claimed 4.12. It also shipped both wheels, 54 MB
plus 82 MB, so the saving the swap existed for was *negative*.

The fix is to not do the clever thing: keep the pin on `opencv-contrib-python`, which satisfies
mediapipe at the verified version and installs one copy. The Dockerfile now asserts
`cv2.__version__` starts with `4.12` at build time, so the build fails rather than the verdicts
drifting.

**What I take from it.** Pinning a package does not pin the library it provides when something
else in the tree can install a different distribution into the same namespace. And a container
that agrees with your build on everything except the answers is the worst possible outcome:
health checks pass, the pipeline runs, the numbers are subtly different. The only reason this was
caught is that the end-to-end test prints verdict counts and I had the host's numbers memorised
from earlier runs. A test that asserted "22 findings returned" would have passed.

## The mistake I am least comfortable about

The two above are mistakes in *my process*. This one had been **shipping a coaching verdict that
was never valid**, and I only found it because I stopped trusting a passing test suite and ran the
real thing. It also cost me two wrong diagnoses before the data settled it, which is the part worth
reading.

Everything had been verified through Python. `scripts/test_client_path.py` proved the
browser-landmark path reproduces the server path's verdicts exactly - all 22 identical. But it
generates the landmarks with **native** MediaPipe, and production compiles the same model to WASM
and runs it in a browser. That is the path every real user hits, and nothing had ever executed it.

So I wrote `frontend/tests/browser-path.spec.ts`: start both services, open real Chromium, upload
the real clip, let the browser do the pose estimation, compare every verdict to the committed
baseline. It failed on its first real run:

```
rep2.hip_drive: cannot_assess (null) -> does_not_meet_standard (0.4074)
```

Native MediaPipe abstains on repetition 2's hip drive. The real browser publishes a confident
"you did this wrong". Same video, same rules.

**Wrong diagnosis one.** The hip-drive ratio needs the shoulders to rise at least 0.02 shin-lengths
before it means anything, which on this clip is 5.2 px. I concluded a few pixels of landmark noise
were deciding between "cannot say" and a failure, built a tidy argument that the floor should be
set by noise (the ratio's relative error is about `sigma / shoulder_rise`, so the rise should clear
roughly ten times landmark jitter), raised it to 0.06, and re-ran.

The ratio came back `0.4074`. Identical to the digit. **The fix had changed nothing, which
disproved the reasoning behind it**: the browser's shoulder rise was *above* 0.06 while native's was
*below* 0.02, a threefold difference rather than a borderline one. I reverted it. A threshold change
whose stated justification has been refuted is just fitting the code to a failing test, and keeping
it would have been the more comfortable option.

**What it actually was.** I made the test dump the browser's own report and diffed it:

| | browser | native |
|---|---|---|
| repetition 1 bottom frame | 66 | 65 |
| repetition 2 bottom frame | 190 | 188 |
| repetition 2 shoulder rise | 0.186 shin | under 0.02 shin |
| shin length | 172.4 px | 259.2 px |

The shin difference is expected and harmless - the browser tracks a 720-wide downscale and
259.2/172.4 is 1.503, exactly the scale factor, which is why every shin-normalised measurement
agrees. The real cause is that **the bottom of a squat is the peak of a nearly flat curve, so its
frame index is only determined to within a frame or two.** Hip drive read a fixed 150 ms window
*starting at that frame* - precisely where the shoulder accelerates hardest. A two-frame shift moved
the shoulder rise by a factor of nine.

The metric now measures its own stability: it recomputes the ratio across the frames the bottom
could plausibly be (plus or minus two, taken from the disagreement above rather than guessed) and
refuses to publish a verdict that the frame choice decides.

**And that is what makes it the uncomfortable one.** Repetition 1's hip-drive ratio ranges from
**0.36 to 1.85** across those frames - straddling the pass/fail threshold of 1.0 - and it had been
reported all along as a confident `does_not_meet_standard` at 0.696. It was never a verdict. Both
repetitions now abstain, the counts move from 13/6/3 to 14/6/2, and both paths agree on all 22.

**What I take from it.** The specific lesson is that a verdict read over a short window anchored at
an ill-determined frame index is fragile by construction, and no amount of agreement between two
runs of the *same* backend will show it. The general one is worse, and is now in
`BUILD_NOTES.md` under Known limitations: **nothing in this project ever asked whether a verdict was
stable under the uncertainty of its own inputs.** Hip drive is simply where a second pose backend
made that fragility visible. Depth, back angle and knee position are all read at `bottom_frame`
too. They should be far less sensitive because they are positions rather than rates, but that is an
argument, not a measurement.

## Two more from the same session, both found by a question rather than a test

Recorded briefly because they share a shape: the code was confident, the tests were green, and a
question about whether the output made sense was what exposed them.

**A target position no human could reach.** The solver produces a corrected pose from the athlete's
own segment lengths, and `scripts/test_target_pose.py` confirmed it was geometrically valid: bone
lengths preserved to 0.00%, foot planted to 0.01 px, depth achieved, other criteria still inside
tolerance. Asked whether the ideal position was physically possible, I measured it and it was not:
the target demanded a **54.7 degree shin lean against the 38.6 the athlete showed**, roughly 16
degrees more ankle dorsiflexion than they had demonstrated. Reaching it would lift the heel, which
breaks the document's own feet-flat requirement (ref p.23). The cause was one of my own residual
terms pulling the hip toward the midfoot, which blocked the hips travelling back and left the knees
going forward as the only route to depth - the opposite of what the document prescribes (ref p.33).
The ankle limit is now taken from the lean the athlete actually held with the heel down, because
their own demonstrated range is evidence where a population figure is a guess about them.

**Measuring the walk-out as part of the lift.** Asked whether the app would work on a different
video, I ran a real gym clip and it returned a confident bar-path failure that was not credible for
a coaching demonstration. Two diagnoses were wrong first: reading an exported frame, I blamed
background plates on the rack, then a bystander standing in shot. Measurement refuted both - the
tracked shoulder travels 915 to 1383 px with no frame-to-frame jump above 200 px, and every
worst-case deviation was a real detection within 55 px of the athlete's own shoulder. The trail I
had misread was the athlete's own walk-out. The actual cause: repetition boundaries came from
hip-height troughs, and **lifting a loaded bar off the pins raises the hips above standing, so the
un-rack is a trough** - and so is the re-rack. Repetition 1 was handed a 156-frame "descent" that
was mostly walking out of the rack. Bar path is a maximum-deviation measurement, so walking
sideways guaranteed a large one, and heels-flat took its standing reference from a frame where the
heel was already raised.

The pattern across all three: **my own diagnostic instincts were wrong more often than the code
was.** Five separate times this session I formed a confident explanation from reading output or
looking at an image, and measurement contradicted it. The fixes that stuck were the ones where I
went and got the numbers first.

## Corrections still open

- Pose gives a hip *centre*, not the hip *crease* the document's depth standard refers to. This is a
  known systematic bias, documented in BUILD_NOTES rather than silently absorbed into a tolerance.
- **Hip drive now reports nothing on the common sample.** Abstaining is the honest answer to a
  ratio that swings from 0.36 to 1.85 with the bottom frame, but it is not a good answer. Anchoring
  the window by hip *displacement* instead of a fixed 150 ms from an uncertain frame should make the
  criterion stable enough to report again. Not attempted: it is a redesign of a measurement, and
  doing it without re-verifying both paths would be worse than the abstention.
- **No other criterion checks its own stability.** Hip drive does only because a second pose
  backend forced the question.
- **Every tolerance is still uncalibrated.** They are all tagged `engineering_tolerance` and none
  has been fitted to labelled footage, because there is none. This is why a criterion sitting near
  its threshold is reported as too close to call rather than resolved.
