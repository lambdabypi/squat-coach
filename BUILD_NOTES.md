# Build notes

## Time spent

**4h 00m** against a self-imposed 5-hour hard stop (the brief allows 4–6). Start 17:31, finish
21:31, same day. A full block-by-block log with actual versus planned times is in
[`TIMELOG.md`](TIMELOG.md), and the original stack/structure plan in [`PLAN.md`](PLAN.md).

Where it went, and where it went wrong:

| Block | Planned | Actual | |
|---|---:|---:|---|
| Read brief + reference, choose stack, plan | 0:20 | 0:09 | |
| Scaffold, install, smoke-test pose and bar detection | 0:20 | **1:03** | +43 over — see "the expensive mistake" |
| Document → agent skill | 0:30 | 0:09 | generated the coverage/citation docs from the YAML instead of writing them |
| Vision core + bar tracking (merged) | 1:15 | 0:50 | |
| Agent, API, frontend | 1:30 | 1:05 | |
| Evidence, correctness fixes, docs | 0:45 | 0:44 | |

The single overrun was block 1, and it was caused by trusting a green metric — the detail is in
[`AI_USAGE.md`](AI_USAGE.md). I absorbed it by generating documentation from the skill YAML rather
than hand-writing it, and by cutting the rendered-MP4 stage (below).

## What was cut, and why

- **Rendered annotated MP4.** The primary annotation is a canvas overlay synchronised to the
  original video. The brief accepts "playable annotated video *or* synchronized video overlays",
  and the overlay is strictly better here: instantly available, sharp at any size, scrubbable, and
  it costs no encode time per video. A downloadable MP4 was cut at the 20:28 boundary.
- **Hosting.** Reproducible local launch only, which the brief explicitly permits. Two services
  and a 31 MB model made a same-day deploy a poor use of the remaining budget.

## Architecture

```
Browser ──upload──▶ FastAPI ──▶ probe ──▶ pose + bar (one decode pass) ──▶ reps
                                                                            │
   ◀──overlay.json──┐                        quality gates ◀────────────────┘
   ◀──report.json───┤                              │
                    └────── Claude ◀── deterministic rule engine
```

**Two services.** Next.js is UI only — no secrets, no inference. FastAPI owns the vision, the
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
| OpenCV HoughCircles + darkness scoring | A loaded plate is a large dark circle at shoulder height — a real observation of the bar, not a shoulder-offset guess. Bar path over the midfoot is a named requirement. | Fails on bumper-free bars and dark gyms; falls back to a labelled estimate. |
| Claude `claude-sonnet-5` | Judgment, grounding and phrasing at low latency and low cost. Prompt caching on the skill block. | — |
| Next.js + hand-written CSS | One less build-config risk inside a 5-hour box. | No design system. |
| In-memory job store | A queue is not what this exercise tests. | Restart loses jobs; single process only. |

### Where the LLM is, and is not

**It never measures.** Every number in the report comes from `vision/metrics.py`. The agent
receives an evidence JSON plus the relevant skill rules and returns findings through a tool
schema validated by Pydantic.

**It may only abstain.** The agent can move a verdict to `cannot_assess` and do nothing else: it
cannot upgrade an abstention into a verdict, and it cannot flip *meets* to *does not meet* or back.
Those two come from arithmetic on a measurement and a declared threshold, and the model has no
information the rule engine lacks — letting it disagree there would be a language model overruling
a comparison it cannot see better than the code that made it.

The guard is enforced in code, not in the prompt (`merge_verdict` in `assess.py`), and every
rejected attempt is recorded in `agent_note`. It is covered by
`scripts/test_confidence_guard.py`, which exists because on a clean run the guard never fires —
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
the obvious optimisation target — run Hough every N frames and interpolate, or seed a CSRT tracker
between detections — and it was not worth the remaining budget.

**Per-video LLM cost, measured on the common sample:**

```
input 11,938 · cache write 4,436 · cache read 0 · output 3,755  ->  $0.1088
```

Two corrections to what I estimated before measuring, both in the same direction: I predicted
5–8s for the agent and it took **33s**, and I predicted "comfortably under $0.05" and it was
**$0.1088** — about double. The output is larger than I assumed because the agent writes an
explanation and an uncertainty note for all 22 findings, not just the interesting ones.

Cache read is 0 on a first run; the skill block (~4.4k tokens) is cached thereafter, so subsequent
videos in the same session cost roughly $0.09. Cost scales with repetition count, since findings
are per rep × criterion — a 5-rep set would be around $0.25.

At consumer volume that is the dominant unit cost and would need attention: batching reps into one
finding per criterion, or dropping narration for `cannot_assess` findings where the rule engine's
wording is already adequate, would cut it by more than half. The figure is measured per run and
reported in `report.cost`, never estimated.

## What I verified

- **Pose:** 236/236 frames detected on the common sample; camera-facing side correctly identified
  as LEFT with a 0.561 visibility margin; per-joint visibility inspected rather than averaged.
- **Bar tracking:** median radius 169px matches the true plate (the broken version locked onto 306
  and 322px background circles). Bar-x standard deviation fell from **231.8px to 29.4px** on a
  1080px-wide frame — the test being that a correct squat's bar path is near-vertical.
- **Landmark overlays** checked frame by frame against the video, not just counted.
- **The refusal path**, on two deliberately difficult recordings — see `EVIDENCE/`.
- **End-to-end on a genuinely uploaded file** via `scripts/e2e_test.py`: upload → poll → report →
  overlay → byte-range video streaming, all against the running API.
- **Overlay JSON is browser-safe** — NaN and Infinity are valid Python floats and would silently
  break `JSON.parse`, so this is asserted in the e2e test.
- **The agent stage**, against the live API: all 22 findings narrated, verdicts **identical** to
  the rule engine's, feedback paraphrasing the document's own coaching language, and measured cost
  recorded above.
- **The confidence guard**, all 9 transitions (`scripts/test_confidence_guard.py`).
- **That editing the skill changes the assessment** (`scripts/test_skill_edit.py`): back-angle
  tolerance 15 → 5 flips both repetitions from *meets* to *does not meet*, and the loader rejects a
  tolerance that claims `document_stated` provenance.
- **The agent failure path, under a genuine failure** rather than a simulated one — see
  `AI_USAGE.md`.

## Correctness problems I found and fixed

All four were found by reading results that the code reported as successes.

1. **Barbell detector reported 5/5 while being wrong on 3 of 5.** Search region was bounded
   vertically but not horizontally, so gym equipment competed with the plate. Fixed by anchoring
   the ROI to the shoulder landmark and sizing it by the athlete's torso. Full account in
   `AI_USAGE.md`.
2. **Hip-drive ratio of −8.96** reported as a confident failure. The guard on a near-zero
   denominator was `1e-6` pixels — meaningless. Now requires shoulder rise above 0.02 shin-lengths
   or it returns `cannot_assess`.
3. **Bar placement failed on every repetition.** The threshold fired because a correctly placed
   low bar rides above the pose model's shoulder *joint centre* — it was measuring anatomy, not a
   fault. With no labelled footage to calibrate against, this criterion now always returns
   `cannot_assess` and reports the measurement as evidence instead.
4. **Eye gaze passed on footage where the head is entirely behind the plate.** MediaPipe reports
   visibility 1.00 for head landmarks it is inferring. Now checks whether the nose falls inside the
   detected plate and abstains if so.

A fifth, found while testing the difficult recordings: the camera-angle gate asserted "this is not
a side view" for a video that was merely too dark and badly cropped. The angle test is derived from
landmark positions, so it cannot be trusted when the person is barely detected. It now defers to
the detection gate — a confident diagnosis from unreliable inputs being the exact thing these gates
exist to prevent.

## Known limitations

**Measurement**

- 2D monocular pose: no true joint centres, no depth, no out-of-plane correction.
- The document's depth landmark is the hip **crease** (Fig 2-1); the model gives a hip **joint
  centre**, which sits higher. This biases depth toward "not deep enough". It is reported as a
  systematic bias on the criterion rather than absorbed into a tolerance — which is why both
  repetitions of the common sample return `cannot_assess` for depth at ±0.02 shin-lengths.
- Bar detection assumes a visible plate.
- Rep segmentation assumes a continuous set in frame; walk-outs and re-racks can produce phantom
  repetitions.

**Coverage**

- Three of the document's eight headline criteria — knees-out, stance, rack height — are
  structurally unassessable from a side view. See `skill/coverage.md`.
- Two more, bar placement and eye gaze, are capped at low confidence and usually abstain.

**Engineering**

- In-memory jobs; no auth, no persistence, no queue; single process.
- Thresholds not present in the document are engineering tolerances, labelled everywhere they
  appear, including in the UI.
- No automated test suite. Verification was scripted and manual — `scripts/test_vision.py`,
  `scripts/e2e_test.py`, `scripts/check_video_serving.py` — which is a real gap rather than a
  deliberate trade-off I would defend in a longer build.

## If I had the next four hours

1. Make pose+bar real-time-ish: detect the plate every N frames, track between detections.
2. A labelled clip set with known-correct verdicts, so tolerances stop being judgement calls.
3. Calibrate bar placement properly, or drop the criterion honestly rather than abstaining.
4. Depth measured from a hip-crease estimate rather than the joint centre, which would move the
   most important criterion off `cannot_assess` for borderline repetitions.
