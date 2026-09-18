# Build notes

## Time spent

**5.6 hours total**, against the brief's 4-6 hour box, in two sessions:

| | |
|---|---|
| **~2h 40m** | to the first complete working build: skill, vision core, bar tracking, agent, API, frontend, evidence runs and docs |
| **~2h 55m** | deployment, the browser-pose rewrite for speed, the report restructure, and the defects found by testing a second video |

An earlier version of this file reported the 2h 40m figure alone. That covered only the first
session and understated the total, which matters because the brief asks for actual time. The
correction is recorded rather than quietly edited: the git history spans 17:31 on 2026-09-17 to
05:16 on 2026-09-18 across 32 commits, an 11.76 hour wall-clock span containing two sessions and
a long break between them.

The 5.6 hours is active working time, and it is my own account rather than something git can
prove. Commit timestamps bound the sessions but cannot separate working-without-committing from
being away from the desk, and there were further breaks inside the committing stretches that
leave no trace. The derivation and its limits are in [`TIMELOG.md`](TIMELOG.md).

Most of the second session was driven by review questions rather than the original build: deploy
it, make it faster, try a different video, is the target pose physically possible. That is where
the most interesting defects surfaced, including two that a single test clip could never have
exposed.

A full block-by-block log with actual versus planned times is in [`TIMELOG.md`](TIMELOG.md), and
the original stack/structure plan in [`PLAN.md`](PLAN.md).

Where it went, and where it went wrong:

| Block | Planned | Actual | |
|---|---:|---:|---|
| Read brief + reference, choose stack, plan | 0:20 | 0:09 | |
| Scaffold, install, smoke-test pose and bar detection | 0:20 | **1:03** | +43 over - see "the expensive mistake" |
| Document → agent skill | 0:30 | 0:09 | generated the coverage/citation docs from the YAML instead of writing them |
| Vision core + bar tracking (merged) | 1:15 | 0:50 | |
| Agent, API, frontend | 1:30 | 1:05 | |
| Evidence, correctness fixes, docs | 0:45 | 0:44 | |
| *Unplanned:* manual testing and the bugs it found | - | 1:25 | CORS, API key scope, model switch |
| *Unplanned:* live angles, corrected pose, live tracking | - | 0:40 | |
| *Unplanned:* deterministic summary, final verification | - | 0:25 | |

The single overrun was block 1, and it was caused by trusting a green metric - the detail is in
[`AI_USAGE.md`](AI_USAGE.md). I absorbed it by generating documentation from the skill YAML rather
than hand-writing it, and by cutting the rendered-MP4 stage (below).

## What was cut, and why

- **Rendered annotated MP4.** The primary annotation is a canvas overlay synchronised to the
  original video. The brief accepts "playable annotated video *or* synchronized video overlays",
  and the overlay is strictly better here: instantly available, sharp at any size, scrubbable, and
  it costs no encode time per video. A downloadable MP4 was cut at the 20:28 boundary.
- **Auth, a database, and a result cache.** None appear anywhere in the brief, and it asks for
  "the smallest implementation that proves the complete experience" (p.1) while stating that "a
  simpler application with verified results will score above a polished one" (p.3). Each was
  considered and declined on that basis:
  - *Auth.* The submission requirement is a working link with any access instructions. There is
    no multi-user or privacy requirement to serve, so a public link satisfies it.
  - *A database.* Reports live in an in-memory job map plus the container filesystem. The
    consequence is real and is documented under Known limitations rather than engineered away:
    Cloud Run scales to zero, so a report link does not survive the instance.
  - *A result cache.* The measurement core is deterministic - `scripts/check_determinism.py`
    confirms three runs of the common sample agree on every verdict, measurement and confidence
    level - so re-uploading a file cannot change the answer, only spend the compute again. A
    content-hash cache would therefore be pure savings, and cost *is* an evaluation axis (p.3).
    It was still declined: the demo includes "show how a change to the skill affects the
    assessment", and a cache puts a staleness risk directly on the path of that demonstration.
    Keyed correctly it would be `hash(video) + skill version`, which is the note worth having
    rather than the code.
- **Hosting was cut, then reinstated.** Originally a reproducible local launch only, which the
  brief explicitly permits. It is now deployed: Vercel for the frontend, Cloud Run for the API.
  The browser-pose path is what made this viable, since server-side analysis on Cloud Run's
  shared vCPUs takes 302s against 88.6s locally.

## Architecture

```
Browser ──upload──▶ FastAPI ──▶ probe ──▶ pose + bar (one decode pass) ──▶ reps
                                                                            │
   ◀──overlay.json──┐                        quality gates ◀────────────────┘
   ◀──report.json───┤                              │
                    └────── Claude ◀── deterministic rule engine
```

**Two services.** Next.js is UI only - no secrets, no inference. FastAPI owns the vision, the
skill and the agent together, so "edit a rule, re-run, watch the assessment change" is a
single-service operation. That matters because the reviewer is expected to do exactly that live.

**One decode pass.** Video decode dominates cost, so barbell detection piggybacks on the pose
pass through a frame sink rather than re-reading the file. Seeking with
`cap.set(CAP_PROP_POS_FRAMES)` on VP9 costs roughly a second per seek and was the main driver of
the block-1 overrun; the pipeline now reads strictly sequentially.

### Model and tool choices

| Choice | Why | What I gave up |
|---|---|---|
| MediaPipe Pose Landmarker (heavy) | 33 landmarks **with per-landmark visibility**. That score is what makes "observed vs estimated" and `cannot_assess` possible at all. | Slower than `lite`/`full`; 2D only. |
| OpenCV HoughCircles + darkness scoring | A loaded plate is a large dark circle at shoulder height - a real observation of the bar, not a shoulder-offset guess. Bar path over the midfoot is a named requirement. | Fails on bumper-free bars and dark gyms; falls back to a labelled estimate. |
| Claude `claude-haiku-4-5` | This stage does constrained work - judge a supplied measurement against a supplied rule, then write two sentences. The cheapest current model is the right default. Override with `ANTHROPIC_MODEL`. | Needed one extra prompt rule the larger model didn't (below). |
| Next.js + hand-written CSS | One less build-config risk inside a 5-hour box. | No design system. |
| In-memory job store | A queue is not what this exercise tests. | Restart loses jobs; single process only. |

### Where the LLM is, and is not

**It never measures.** Every number in the report comes from `vision/metrics.py`. The agent
receives an evidence JSON plus the relevant skill rules and returns findings through a tool
schema validated by Pydantic.

**It may only abstain.** The agent can move a verdict to `cannot_assess` and do nothing else: it
cannot upgrade an abstention into a verdict, and it cannot flip *meets* to *does not meet* or back.
Those two come from arithmetic on a measurement and a declared threshold, and the model has no
information the rule engine lacks - letting it disagree there would be a language model overruling
a comparison it cannot see better than the code that made it.

The guard is enforced in code, not in the prompt (`merge_verdict` in `assess.py`), and every
rejected attempt is recorded in `agent_note`. It is covered by
`scripts/test_confidence_guard.py`, which exists because on a clean run the guard never fires -
meaning it would otherwise be untested exactly when it matters. Writing that test is what caught
the flip case: the original implementation ranked `meets` and `does_not_meet` as equally
confident and so allowed the agent to swap them.

On schema failure: one repair round-trip, then the deterministic verdicts ship with a note saying
the wording is plainer. The system degrades to something true rather than something fluent.

## Performance and cost

Measured on the common sample (1080×1920, 30fps, 7.9s, 236 frames), CPU only, no GPU:

| Stage | Time |
|---|---|
| Probe | <0.1s |
| Pose + bar detection | ~60s (≈7.5× clip duration) |
| Reps, quality, rules | <0.5s |
| Agent | ~33s |
| **Total** | **93s with the agent, 60s without** |

Pose inference is ~15fps on its own; adding per-frame Hough detection drops it to ~4fps. That is
the obvious optimisation target - run Hough every N frames and interpolate, or seed a CSRT tracker
between detections - and it was not worth the remaining budget.

**Per-video LLM cost, measured on the common sample with `claude-haiku-4-5`:**

```
input 13,058 · cache write 0 · cache read 0 · output 2,886  ->  $0.0275
```

Three corrections, each found by measuring something I had asserted:

1. **I predicted 5-8s for the agent; it takes ~25-33s.** The output is larger than I assumed
   because the agent writes an explanation and an uncertainty note for all 22 findings, not just
   the interesting ones.
2. **My price constants were wrong.** I had `claude-sonnet-5` hard-coded at $3/$15 per MTok when
   it is $2/$10, which overstated every reported cost by ~50%. Pricing is now a per-model table,
   and an unrecognised model reports token counts with a `null` dollar figure rather than a
   fabricated one.
3. **Prompt caching does not apply at this size.** The skill block is **2,053 tokens**, below
   `claude-haiku-4-5`'s minimum cacheable prefix, so the `cache_control` breakpoint is silently
   ignored - `cache_write` and `cache_read` are both 0 on every call, verified over two identical
   requests in `scripts/test_cache.py`. An earlier draft of this document claimed the skill block
   was cached across videos. It is not, on this model. The breakpoint is harmless and starts
   working if the skill grows or a larger model is configured.

Cost scales with repetition count, since findings are per rep × criterion - a 5-rep set is around
$0.06. At consumer volume the obvious reductions are batching reps into one finding per criterion,
or skipping narration for `cannot_assess` findings where the rule engine's wording is already
adequate. The figure is measured per run and reported in `report.cost`, never estimated.

**Cost to build.** Under **$1** in Anthropic API charges across the whole session: roughly 20 full
pipeline runs with the agent enabled at $0.026 each, plus a handful of sub-cent connectivity
checks. Everything else in the build is free: MediaPipe, OpenCV, FastAPI and Next.js are
open-source, the pose model is a 31 MB download, and all compute ran locally on a laptop CPU. The
assistant time used to write the code is not metered per video and is not included in that figure.

**On model choice.** Haiku 4.5 costs a third of Sonnet 5 here and produced identical verdicts -
unsurprising, since it does not decide verdicts. It did need one prompt rule the larger model did
not: its first summary said depth was *"too close to the camera to call"* when the evidence said
too close to the *tolerance*. Those are different findings, and conflating them is exactly the
error this application exists to avoid. The system prompt now forbids substituting a cause for a
`cannot_assess`, and the summary instruction separates the two kinds of "we don't know". A larger
model is one env var away (`ANTHROPIC_MODEL=claude-sonnet-5`) if that trade looks wrong.

**The prompt fix was only partial, so the summary was taken away from the model entirely.**
After the prompt change the summary led with the correct reason ("the depth measurements sit right
at the edge of our tolerance") but was still observed appending "from this camera angle" to it. The
per-finding explanations were correct in every run; the drift was confined to the free-text
summary - which is the most-read paragraph in the report.

Rather than keep asking a prompt to hold a distinction, `skill/summary.py` now builds the summary
from the counted findings. The three reasons a verdict can be withheld are **separate lists built
from separate conditions**, so they cannot bleed into one another:

| Reason | What it means | What fixes it |
|---|---|---|
| Inside measurement tolerance | We measured it; the value is too close to the line to call | Nothing the athlete can film differently |
| Evidence missing in this clip | The landmark was occluded in the frames we needed | Re-record with better framing or lighting |
| Structurally unassessable | A sagittal camera cannot see this property at all | A different camera angle |

The agent still writes every per-finding explanation and every piece of coaching feedback; only
the roll-up moved. `scripts/test_summary.py` asserts the distinction survives into the prose - it
fails the build if a tolerance-bound result is described in camera language.

This removed a failure mode rather than adding a feature, and it made the output slightly cheaper
($0.0256 from $0.0275) because the model writes fewer tokens.

Writing the deterministic version surfaced two things the model had been papering over: a
criterion can fail on one repetition and be unmeasurable on another, which reads as a
contradiction unless stated explicitly; and several criterion names contain "and"
("stance width and toe angle"), so a comma-and list of them is unparseable and needs semicolons.

## Why the language model never sees the video

Worth stating plainly, because it is the question the architecture most often gets asked.

**Haiku 4.5 is not used as a VLM.** It receives a JSON object of measurements and the skill's
rules, and returns prose. No frame, no image block, no video reaches it. The seeing is done by
MediaPipe Pose Landmarker and OpenCV.

That is not a cost decision - at low frame counts a VLM is actually *cheaper*, and
`scripts/cost_model.py` says so:

| Approach | Cost per video |
|---|---:|
| Shipped: pose + CV locally, LLM narrates numbers | **$0.0275** |
| VLM, 4 downscaled frames, Haiku 4.5 | $0.0198 |
| VLM, every 3rd frame, Haiku 4.5 | $0.2327 |
| VLM, every frame, Haiku 4.5 | $0.6695 |
| VLM, every frame, Opus 5 | $3.35 |

(Image tokens from Anthropic's documented `width × height / 750`; a 1080×1920 frame is ~2,765
tokens. Local pose and CV cost nothing in API charges - roughly $0.0008 per video at commodity
CPU rates.)

The four-frame VLM wins on price and loses on everything that matters here:

- **No per-landmark visibility score.** That single signal is what drives `observed` vs
  `estimated` and every `cannot_assess` verdict in this system. A VLM has no equivalent - it is
  equally fluent whether it can see the joint or not.
- **No pixel-level joint location.** "Hip 0.019 shin-lengths below knee" becomes "looks about
  parallel", and the borderline depth call - the most interesting result on the common sample -
  disappears.
- **No bar path.** Tracking the plate across 236 frames is what produces a path at all.
- **Nothing to check.** A landmark can be drawn on the frame and verified by eye; that is how
  four of the five bugs above were caught. A claim cannot be verified this way.

Giving a VLM enough frames to do those things costs 24× the shipped design and still yields
estimates rather than measurements.

### Running locally on edge hardware

The natural extension, and the strongest version of the "use a better vision model" argument, is
NVIDIA Jetson-class hardware on-site: no per-video API cost, no upload latency, and no footage of
someone's body leaving the gym - which is a real consideration for this product.

With a GPU available I would swap MediaPipe for **Meta's Sapiens** (human-centric foundation
model, materially better on occluded joints - our weakest point, and why knee visibility drops to
0.84 on the common sample) and run a local model for narration. The marginal cost goes to zero.
The structure does not change: a specialist vision model measures, a language model explains, and
the language model still never sees a pixel.

## Showing the work: live angles and the corrected pose

Two additions that make the system's reading inspectable rather than merely reported.

**Live angles.** Every overlay frame carries back angle, knee angle, hip angle and signed bar
deviation from the midfoot, computed from the same smoothed series the assessment uses - not a
parallel calculation that could drift from it. On the canvas: an arc at the hip, dashed guides at
hip and knee height that make the depth standard legible frame by frame, and a plumb line through
the midfoot the bar should track along. Below, a readout comparing each value to the skill's
reference, with tolerances still labelled as ours.

**The corrected pose, and why it is not a 3D animation.** A canned 3D animation would be generic
reference content: the same clip for every user, derived from nothing they did - precisely the
"generic squat advice" the brief rules out. It would also render a depth dimension a single
side-on camera never measured.

Instead we solve a two-link IK problem constrained by *this athlete's* measured tibia, femur and
torso lengths, with their foot planted where it actually was, for the criteria their repetition
actually failed - and draw the result as a ghost on their own bottom frame. The solve starts from
the observed angles, so it returns the *nearest* compliant pose: the smallest correction that
works, not an arbitrary valid one.

It also refuses to fix one criterion by breaking another. Deepening a squat with a planted foot
drives the knee forward, so a one-sided penalty holds the knee inside the limit the skill declares.
It exists so a different body cannot be handed advice that violates a rule it was passing.

`scripts/test_target_pose.py` re-measures the solved pose against the same rules: bone lengths
preserved to 0.00% drift, ankle planted to 0.01px, depth corrected from +0.022 to +0.060
shin-lengths (clearing the 0.03 tolerance), knee and back angle both still compliant.

**A geometrically valid target that no human could reach.** All of the above passed while the
target was biomechanically wrong, and it took the user asking "is the ideal position even
possible for a human?" to find it. The original residuals pulled the hip toward the midfoot on
the reasoning that a balanced squat stays over the foot. That term stopped the hips travelling
*back*, so the only remaining route to depth was the knees going *forward*, and the solver duly
asked for a **54.7 degree shin lean against the 38.6 the athlete showed - 16 degrees more ankle
dorsiflexion**, with the knee travelling from 0.17 to 0.35 shin-lengths past the toe. Sixteen
degrees is not a cue anyone can apply; reaching it lifts the heel, which breaks the document's own
feet-flat requirement (ref p.23). The target satisfied depth by quietly violating a criterion it
was not checking, and the document actually prescribes the opposite: "sit back, lean forward, and
shove your knees out" (ref p.33).

`test_target_pose.py` could not have caught this. It asks whether the pose is *geometrically*
valid - bones preserved, foot planted, depth met, other criteria inside tolerance - and the pose
was all of those. Achievability is a different question, so it needed a different script:
`scripts/check_target_feasible.py`.

Two changes, both one-sided limits rather than targets:

- **Ankle range, measured from the athlete.** A population dorsiflexion figure would be a guess
  about this person. Their own deepest observed shin lean, held with the heel down, is evidence.
  The solver may ask for that plus `ANKLE_ALLOWANCE_DEG = 4` and no more.
- **Balance, as a limit.** Removing the midfoot pull meant depth now comes from the hips going
  back, so the failure mode inverted: not a knee past its limit but a hip so far back the athlete
  sits down. `BALANCE_LIMIT_SHIN = 0.60` catches that without prescribing posture.

After the fix, on the common sample: **shin lean 38.6 -> 38.6 degrees (no extra dorsiflexion
asked for), knee 0.168 -> 0.168 shin-lengths (it does not move at all), hip 0.444 -> 0.442
shin-lengths behind the midfoot (balance unchanged), and depth still reached at exactly 0.060.**
The whole correction is the hip dropping 0.038 shin-lengths - small, balanced, and inside range
the athlete had already demonstrated on camera.

Two honest leftovers. First, depth is *almost always* reachable by rotating the femur, so the
`depth_limited` path - which reports "this needs mobility work, not a cue" and names whether the
ankle or balance bound - does not fire on either sample repetition and is therefore untested on
real input. Second, the observed lean of 38.6 degrees already **exceeds** the 35-degree population
shod-dorsiflexion reference. Either that reference does not describe this athlete or the 2D view
inflates the angle; `check_target_feasible.py` prints this as context rather than a verdict,
because the athlete demonstrably held the position on video. It is the reason the limit is
anchored to their own measurement instead of a published range.

One bug found on the way out: the new fields carried `np.float64` and `np.bool_`, which `json`
refuses. Because numpy 2 reports `np.bool_`'s type name as plain `bool`, the error reads
"Object of type bool is not JSON serializable" - self-contradictory, and it would have surfaced
in the API response rather than at the point of construction. `run_cli.py` exposed it only
because `report.json` was written and `overlay.json` was not.

## What I verified

- **Pose:** 236/236 frames detected on the common sample; camera-facing side correctly identified
  as LEFT with a 0.561 visibility margin; per-joint visibility inspected rather than averaged.
- **Bar tracking:** median radius 169px matches the true plate (the broken version locked onto 306
  and 322px background circles). Bar-x standard deviation fell from **231.8px to 29.4px** on a
  1080px-wide frame - the test being that a correct squat's bar path is near-vertical.
- **Landmark overlays** checked frame by frame against the video, not just counted.
- **The refusal path**, on two deliberately difficult recordings - see `EVIDENCE/`.
- **End-to-end on a genuinely uploaded file** via `scripts/e2e_test.py`: upload → poll → report →
  overlay → byte-range video streaming, all against the running API.
- **Overlay JSON is browser-safe** - NaN and Infinity are valid Python floats and would silently
  break `JSON.parse`, so this is asserted in the e2e test.
- **The agent stage**, against the live API: all 22 findings narrated, verdicts **identical** to
  the rule engine's, feedback paraphrasing the document's own coaching language, and measured cost
  recorded above.
- **The confidence guard**, all 9 transitions (`scripts/test_confidence_guard.py`).
- **That editing the skill changes the assessment** (`scripts/test_skill_edit.py`): back-angle
  tolerance 15 → 5 flips both repetitions from *meets* to *does not meet*, and the loader rejects a
  tolerance that claims `document_stated` provenance.
- **The agent failure path, under a genuine failure** rather than a simulated one - see
  `AI_USAGE.md`.

## Correctness problems I found and fixed

All of the first four were found by reading results that the code reported as successes.

1. **Barbell detector reported 5/5 while being wrong on 3 of 5.** Search region was bounded
   vertically but not horizontally, so gym equipment competed with the plate. Fixed by anchoring
   the ROI to the shoulder landmark and sizing it by the athlete's torso. Full account in
   `AI_USAGE.md`.
2. **Hip-drive ratio of -8.96** reported as a confident failure. The guard on a near-zero
   denominator was `1e-6` pixels - meaningless. Now requires shoulder rise above 0.02 shin-lengths
   or it returns `cannot_assess`.
3. **Bar placement failed on every repetition.** The threshold fired because a correctly placed
   low bar rides above the pose model's shoulder *joint centre* - it was measuring anatomy, not a
   fault. With no labelled footage to calibrate against, this criterion now always returns
   `cannot_assess` and reports the measurement as evidence instead.
4. **Eye gaze passed on footage where the head is entirely behind the plate.** MediaPipe reports
   visibility 1.00 for head landmarks it is inferring. Now checks whether the nose falls inside the
   detected plate and abstains if so.

A fifth, found while testing the difficult recordings: the camera-angle gate asserted "this is not
a side view" for a video that was merely too dark and badly cropped. The angle test is derived from
landmark positions, so it cannot be trusted when the person is barely detected. It now defers to
the detection gate - a confident diagnosis from unreliable inputs being the exact thing these gates
exist to prevent.

A sixth, and the only one found by testing a video other than the one this was built on. All the
verification above ran against a single clip, tightly cropped to two repetitions with no un-rack in
frame. Handed a real gym clip from a coaching channel, the assessment produced a confident
`does_not_meet_standard` on bar path at 0.578 shin-lengths, which for a coaching demonstration was
not credible.

**Repetition boundaries were taking in the un-rack, the setup and the re-rack.** `segment_reps`
bounded each repetition with the hip-height *troughs* either side of the bottom. Lifting a loaded
bar off the pins raises the hips *above* standing, so the un-rack is a trough, and so is the
re-rack. Measured on that clip: hip y of 522 at the chosen start against a standing level of about
565, and repetition 1 handed frames 70 to 260 - a 156-frame "descent" that was mostly walking out
of the rack, against a 34-frame ascent.

Three metrics inherited it. Bar path is a maximum-deviation measurement over the repetition, so
walking sideways out of a rack guarantees a large one. Heels-flat takes its standing reference from
`rep.start_frame`, which was the un-rack frame with the heel *already raised*, which is why it
reported the heel travelling *downward* (-0.055 shin-lengths). Bar height relative to the shoulder
uses the same frame. Fixed at the segmenter rather than in each metric: boundaries now pull in to
where the hip has descended 15% past a robust standing level, taken as the 15th percentile of hip
height rather than the minimum, because the un-rack frames sit above standing and would drag the
reference with them. Bar path fell to 0.270 and 0.338, heels-flat to -0.030, and the common
sample's verdict counts did not move (13/6/3), with bar path and depth identical to the digit.

Two things about how this was found are worth more than the fix. First, `BUILD_NOTES.md` already
listed "walk-outs and re-racks can produce phantom repetitions" as a known limitation, written
before there was a second clip to test: the limitation was real and the consequence was
under-estimated, because a phantom repetition is easy to notice and a *contaminated* one is not.
Second, two wrong diagnoses came first. The exported frame showed the bar-path trail wandering onto
the gym's rack, so the first hypothesis was background plates outscoring the real one; the second
was that pose had switched to a bystander standing in shot. Measurement refuted both - shoulder x
travels 915 to 1383 with no frame-to-frame jump above 200px, and every worst-case deviation is
`observed=True` within 55px of the athlete's own shoulder. The trail was the athlete's own walk-out,
drawn from the shoulder fallback. The proximity cutoff added in `bar.py` on the strength of the
first hypothesis is defensible physics and is kept, but it changed this clip's outcome by 0.001
shin-lengths and there is no case on hand where it changes a verdict.

A seventh, and the one I am least comfortable about, because it had been shipping as a confident
verdict and two of my own diagnoses were wrong before the data settled it.

The first real run of the browser test failed: the browser published
`does_not_meet_standard` on repetition 2's hip drive, ratio 0.41, where native MediaPipe abstained.

**Wrong diagnosis one.** The hip-drive guard requires the shoulders to rise at least 0.02
shin-lengths before a ratio means anything, which on this clip is 5.2 px. I decided a few pixels of
landmark noise were deciding between "cannot say" and "you did this wrong", argued the floor should
be set by noise (the ratio's relative error is about sigma/shoulder_rise, so the rise should clear
roughly ten times landmark jitter), and raised it to 0.06. The next run returned ratio 0.4074,
identical to the digit. The fix had done nothing, which disproved the reasoning behind it: the
browser's shoulder rise was above 0.06 while native's was below 0.02, a threefold difference rather
than a borderline one. Reverted, because a threshold change whose justification has been refuted is
just fitting the code to a failing test.

**Wrong diagnosis two.** Before that, on seeing the bar-path trail wander onto the gym's rack in an
exported frame, I had blamed background plates outscoring the real one, and then a bystander
standing in shot. Measurement refuted both.

**What it actually was.** Dumping the browser's own report and diffing it against the baseline:

| | browser | native |
|---|---|---|
| repetition 1 bottom frame | 66 | 65 |
| repetition 2 bottom frame | 190 | 188 |
| repetition 2 shoulder rise | 0.186 shin | under 0.02 shin |
| shin length | 172.4 px | 259.2 px |

The shin difference is expected and harmless - the browser tracks a 720-wide downscale, and
259.2/172.4 is 1.503, exactly the scale factor, which is why every shin-normalised measurement
agrees. The real cause is that **the bottom of a squat is the peak of a nearly flat curve, so its
frame index is only determined to within a frame or two**, and hip drive read a fixed 150 ms window
starting from that frame - the stretch where the shoulder is accelerating hardest. A two-frame
shift moved the shoulder rise from below the abstention floor to nine times it.

So the metric now measures its own stability: it recomputes the ratio across the frames the bottom
could plausibly be (plus or minus two, taken from the disagreement above, not guessed) and refuses
to publish a verdict that the frame choice decides.

**That is what makes this the uncomfortable one.** Repetition 1's hip-drive ratio ranges from
**0.36 to 1.85** across those frames, straddling the pass/fail threshold of 1.0 - and it had been
reported all along as a confident `does_not_meet_standard` at 0.696. It was never a verdict. Both
repetitions now abstain, the counts move from 13/6/3 to **14/6/2**, and the browser and server
paths agree on all 22.

The better fix is to anchor the window by hip *displacement* rather than a fixed time from an
uncertain frame, which would make the criterion stable enough to report again rather than merely
honest about being unreportable. That is a metric redesign needing full re-verification and is
listed under Known limitations instead of half-done.

The general lesson is worse than the specific bug: **nothing in this project checked whether a
verdict was stable under the uncertainty of its own inputs.** Hip drive is simply the criterion
where a short window anchored at an ill-determined frame made that fragility large enough for a
second pose backend to expose. The same question is unasked for every other criterion.

An eighth, worth recording for what it says about the verification rather than about the code: the
live tracking view streamed landmarks back correctly and never painted
them. A React effect guarded on refs that are null while the component renders `null`, with a
dependency list that never changed, so the render loop never started. TypeScript passed. The
preview-endpoint test passed. The end-to-end run passed. **Nothing I wrote exercised the browser
render path**, and no amount of further scripted checking would have caught it - it took someone
opening the page. That is the real gap in this project's verification, and the argument for one
headless-browser smoke test over more unit coverage.

## Mocked components and manual steps

**There are none.** Every stage runs for real on a newly uploaded file: probe, pose, barbell
detection, repetition segmentation, quality gates, measurement, rule evaluation, agent narration,
overlay. `scripts/e2e_test.py` exercises that path against the running API and is the check behind
this claim.

Stated precisely, so it can be held against us:

- **No canned results.** Nothing is read from a fixture. Deleting `EVIDENCE/` changes nothing
  about what the application does.
- **No manual steps inside the flow.** Upload to report is one user action. The only manual setup
  is the documented install: create the venv, install requirements, download the pose model, start
  two servers.
- **No hand-tuning per video.** No parameter is adjusted for the common sample. The two difficult
  recordings were run through the identical code path and refused by it.
- **The agent is real and optional.** It calls the Anthropic API. Without a key the deterministic
  rule engine produces every verdict, measurement, citation and uncertainty note on its own, and
  the interface says so.
- **Two things are computed rather than observed, and both are labelled.** Bar position falls back
  to a shoulder-offset estimate when the plate is not detected, marked `estimated` everywhere it
  appears. Centimetre figures assume a 450 mm plate, stated in the report.
- **Not implemented, and not pretended otherwise:** hosting (local launch only), persistence
  (jobs are in memory), authentication, and any criterion marked `cannot_assess`.

## Known limitations

**Measurement**

- 2D monocular pose: no true joint centres, no depth, no out-of-plane correction.
- The document's depth landmark is the hip **crease** (Fig 2-1); the model gives a hip **joint
  centre**, which sits higher. This biases depth toward "not deep enough". It is reported as a
  systematic bias on the criterion rather than absorbed into a tolerance - which is why both
  repetitions of the common sample return `cannot_assess` for depth at ±0.02 shin-lengths.
- Bar detection assumes a visible plate.
- **Verdict stability is only checked for hip drive.** That criterion now recomputes its ratio
  across the frames the bottom could plausibly be and abstains when the frame choice decides the
  answer. No other criterion asks that question of itself, and the reason hip drive does is that a
  second pose backend happened to expose it. Depth, back angle and knee position are all read at
  `bottom_frame` too; they are far less sensitive because they are positions rather than rates
  measured over a short window, but "less sensitive" is an argument, not a measurement.
- **Hip drive now abstains on both repetitions of the common sample**, so the criterion reports
  nothing there. Anchoring its window by hip displacement instead of a fixed 150 ms from an
  uncertain frame should make it stable enough to report again. Not attempted: it is a redesign of
  a measurement, and doing it without re-verifying both paths would be worse than the abstention.
- Rep segmentation assumes a continuous set in frame. Walk-outs and re-racks can still produce
  phantom repetitions; the boundary contamination described below is fixed, the phantom-rep case
  is not.

**Determinism and persistence**

- The measurement core is deterministic: `scripts/check_determinism.py` runs the common sample
  three times and compares every verdict, measurement and confidence level, and they are
  identical. Re-uploading a file cannot change the result.
- **The narration is not.** Nothing in this codebase sets `temperature`, so the Anthropic default
  of 1.0 applies and the summary *wording* varies between runs even when the verdicts it describes
  do not. The deployed backend runs with no key, so the deterministic summary writer produces the
  text there, but this would want `temperature=0` the moment a key is set.
- **A report does not outlive the instance.** Job state is an in-memory map, and the report page
  fetches `/jobs/{id}/report` and `/jobs/{id}/overlay` as separate requests after navigation.
  Cloud Run runs with `min-instances 0`, so an older report link 404s once the instance is gone.
  This also forced `--max-instances 1`: with two instances those follow-up fetches could land on
  the instance that never saw the job, 404ing a report that had just been generated. There is no
  concurrency requirement here, so pinning to one instance is free. Surviving a restart would
  need the reports persisted server-side, which is the database decision recorded above.

  The browser now keeps its own copy of what it was given, which covers the common case without a
  database: the report and overlay in `sessionStorage`, and the video blob in IndexedDB. A reload
  therefore works, and when it falls back to the stored copy the page says so rather than implying
  the server still has it.

  **This limitation was originally understated, and the correction is worth recording.** It was
  written as a Cloud Run scale-to-zero problem. In use, the video disappeared on reload against a
  *live local backend*, because on the browser-tracking path the file is never uploaded at all: it
  was held in a module-level map that survives client-side navigation and dies on reload, and the
  fallback pointed the player at `/jobs/{id}/video`, which does not exist on that path. So the
  verdicts were intact and the footage they were drawn on was a 404. Reported from real use, not
  from any test, which is the third time in this project that using the product beat the suite.
  The Playwright test now reloads the page and requires the player's source to be a restored
  `blob:` URL.

**Coverage**

- Three of the document's eight headline criteria - knees-out, stance, rack height - are
  structurally unassessable from a side view. See `skill/coverage.md`.
- Two more, bar placement and eye gaze, are capped at low confidence and usually abstain.

**The browser-tracking path**

- **This gap is now closed, and closing it found a defect.** `frontend/tests/browser-path.spec.ts`
  starts both services, opens real Chromium, uploads the clip, lets the browser run MediaPipe WASM
  itself, and compares all 22 verdicts against the committed `EVIDENCE` baseline. It passes, with
  no diverging verdicts.

  On its first real run it failed, and the failure was genuine: the browser published
  `does_not_meet_standard` on repetition 2's hip drive where native MediaPipe abstained. Two wrong
  diagnoses came first. The full account is under "Correctness problems", but the short version is
  that the bottom of a squat is the peak of a nearly flat curve, so its frame index is only
  determined to within a frame or two - measured at 65 vs 66 and 188 vs 190 between the two
  backends on identical footage - and hip drive read a fixed 150 ms window starting from it.

  The test costs about eight minutes per run, because headless Chromium has no GPU delegate and
  runs the WASM build entirely on the CPU. That is too slow for an edit-run loop; treat it as a
  pre-demo or CI check. It dumps the browser's own report to
  `frontend/test-results/browser-report.json` on every run, pass or fail, because the job is gone
  from the server's in-memory map the moment the run ends and a failure that prints only the moved
  verdict otherwise costs a full run per follow-up question.

- **The older equivalence test simulates the browser rather than using it.**
  `scripts/test_client_path.py` proves the client path reproduces the server path's verdicts
  exactly, but it generates the landmarks with *native Python MediaPipe*. The real browser runs
  the same model compiled to WASM, possibly on the GPU delegate. Those are not bit-identical,
  and near a tolerance boundary the difference is enough to change a verdict: on a real browser
  run, repetition 1 measured deep enough for depth to pass while repetition 2 stayed inside the
  0.03 shin-length band and was left open, on two repetitions a viewer would call identical.
  That behaviour is correct - it is the tolerance doing its job - but the test does not cover
  the numerics that produced it. Closing this needs a headless browser running the actual WASM
  build and comparing against the native result.
- **A verdict near the tolerance is not stable across pose backends.** Documented above for
  heavy/full/lite; the browser build is a fourth backend with the same property. The report now
  shows where each correctable criterion landed when no target position is produced, so a reader
  can see a borderline call rather than inferring a bug from a missing panel.

**Engineering**

- **No browser-level test.** Every verification script exercises the backend or the data; none
  opens the page. That is how a render bug shipped past a green suite. One headless-browser smoke
  test that uploads a clip and asserts pixels change on the canvas would close it.
- In-memory jobs; no auth, no persistence, no queue; single process.
- Thresholds not present in the document are engineering tolerances, labelled everywhere they
  appear, including in the UI.
- No automated test suite. Verification was scripted and manual - `scripts/test_vision.py`,
  `scripts/e2e_test.py`, `scripts/check_video_serving.py` - which is a real gap rather than a
  deliberate trade-off I would defend in a longer build.

## Performance, and why it is not simply fixable

The pipeline spends **51% of its time in a classical circle detector**, not in a neural network.
Pose alone runs at 16.3 fps; per-frame HoughCircles drops the pass to 4.1 fps.

Measured options, and the reason the obvious one is not taken:

| Change | Speed-up | Verdicts changed (of 22) |
|---|---:|---:|
| Detect the plate every 5th frame, track between | **2.5x** | **0** (pose untouched) |
| Lighter pose model (`full`) | 1.6x | 4 |
| Lighter pose model (`lite`) | 1.4x | 9 |
| `lite` + every 5th frame + half resolution | 13.2x | not safely measurable |

The 13x configuration runs **faster than real time** on this laptop. It also changes 41% of the
verdicts, and we have no ground truth to say which set is correct. Worse, the disagreement between
pose models on depth is 0.16-0.23 shin-lengths while our depth tolerance is 0.03 - the tolerance
was calibrated against jitter within one model and says nothing about uncertainty across models.

So the shipped configuration keeps the heavy model, and the honest next step is a labelled clip
set rather than a faster one. Full analysis, including the Jetson edge-deployment and VLM costings,
is in [FUTURE_SPEC.md](FUTURE_SPEC.md). Reproduce with `scripts/bench_speed.py` and
`scripts/bench_accuracy.py`.

## If I had the next four hours

*(The first item on this list - generating the summary in code - was done; see above.)*

1. Make pose+bar real-time-ish: detect the plate every N frames, track between detections.
2. A labelled clip set with known-correct verdicts, so tolerances stop being judgement calls.
3. Calibrate bar placement properly, or drop the criterion honestly rather than abstaining.
4. Depth measured from a hip-crease estimate rather than the joint centre, which would move the
   most important criterion off `cannot_assess` for borderline repetitions.
