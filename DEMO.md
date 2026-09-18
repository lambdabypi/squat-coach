# 15-minute walkthrough

~5 minutes on the product and its value, ~10 on the application and how it works. They may supply
a new video or change a rule in the source document during the review — both are rehearsed below.

## Before you start

```bash
# terminal 1
cd backend && export PYTHONPATH=$PWD && export ANTHROPIC_API_KEY=... && uvicorn app.main:app --port 8000
# terminal 2
cd frontend && npm run dev
```

Have ready: the common sample, the front-view clip (`EVIDENCE/hard-sample/`), and
`skill/squat_standards.yaml` open in an editor. Pre-warm one analysis so you are not watching a
progress bar for 60 seconds on camera.

---

## Part 1 — the product (5 min)

**The problem.** Someone films their squat and asks "was that deep enough?". The honest answers
available today are a coach who costs $80/hour, or a forum thread. Consumer form-check apps give
confident-sounding advice from a model that has never read a standard and cannot tell you where
its rule came from.

**The wedge.** Squat Coach assesses against *a specific text* and cites the page. A lifter can
argue with the verdict, follow it back to the source, and decide for themselves. That is a
different product from "AI says your depth is 87%".

**The thing worth pausing on.** Show the coverage table on the landing page. Three of the
document's own eight headline faults — knees-out, stance, rack height — are invisible to a side
camera. Most products in this space quietly score them anyway.

> A tool that tells you what it cannot see is one you can trust about what it can.

**Who pays.** Gyms and remote coaching platforms, where a coach reviews dozens of form checks a
week and needs evidence to point at, not a score.

---

## Part 2 — the application (10 min)

### a) Run the full flow on a new video (2 min)

Upload, narrate the staged progress, land on the report. Emphasise: this ran now, on this file.

### b) The evidence (3 min)

- Toggle skeleton and bar path. Green landmarks were seen; orange were inferred by the model.
- The barbell marker is solid when the plate was detected, dashed when the position is a
  shoulder-offset estimate. **That distinction runs all the way through to the findings.**
- Click a finding's timestamp — the player jumps to the frame the measurement came from.
- Click the citation pill — the verbatim source text.
- Point at a tolerance pill: `our tolerance` versus `per document`. The document states almost no
  numbers; anything numeric that is not in the text is labelled as ours.

### b2) Show the reading, not just the verdict (1 min)

Turn on **Angles**. The back-angle arc at the hip, the knee readout, the dashed guides at hip and
knee height — those two lines *are* the depth standard, visible frame by frame — and the plumb line
through the midfoot that the bar should track. The readout panel compares each to the skill's
reference and still says `our tolerance` where the number is ours.

Scrub slowly through the descent. The point to make: **this is what the system is measuring, live.**
The findings are not a separate opinion produced afterwards.

### b3) The corrected pose (1 min)

Turn on **Target pose** and jump to a rep bottom. The dashed ghost is *their* body — same tibia,
femur and torso lengths measured from this video, same planted foot — solved for the position the
document describes. The arrow runs from where their hip was to where it needed to be.

If asked why it isn't a 3D animation: a stock animation is the same clip for every user and
derived from nothing they did, which is the generic advice the brief rules out. And we only ever
measured two dimensions — rendering a third would be inventing data. Both limits are stated in the
panel.

### c) Why depth says "cannot assess" (2 min)

The best 90 seconds of the demo, because it is the most counter-intuitive result.

Hip and knee landmarks are within 0.02 shin-lengths at the bottom — inside measurement tolerance.
And the document's landmark is the hip *crease* (Fig 2-1, ref p.2) while pose gives a hip *joint
centre*, a few centimetres higher. So a confident verdict either way would be invented. Show the
annotated still: the athlete really is at roughly parallel.

### d) Change a rule live (2 min)

The thing they asked to see. In `skill/squat_standards.yaml`, under `back_angle`:

```yaml
    tolerance:
      value: 15        # change to 5
```

Re-run. Both repetitions flip from *meets standard* to *does not meet* — 59° and 58° were inside
±15 of the document's "about 45", and are outside ±5. **No application code changed.**

Then show the guard: set that tolerance's `provenance` to `document_stated` and restart. The
loader refuses to boot. A tolerance is a measurement margin and the document states none, so that
edit is always a mistake and fails loudly rather than silently mislabelling our number as the
book's.

### e) An incorrect result, investigated (1 min)

Have `AI_USAGE.md` ready. The barbell detector once reported `plate 5/5` while being wrong on 3 of
5 frames; the radii were `164, 306, 294, 306, 168` — two clusters, and a plate can only produce
one. The repair that "fixed" it to 88% was also wrong, because spurious circles outnumbered the
plate 73:42, so the modal radius was the background. The tell was a bar-x spread of 232px on a
1080px frame, when a squat's bar path is near-vertical.

Real bug: the search region was bounded vertically but not horizontally. Anchoring the ROI to the
shoulder took the spread to 29.4px.

### f) A video it should refuse (1 min)

Upload the front-view clip. Detection is 87%, repetitions are found, and it still refuses — on
camera angle alone, with instructions for re-recording. This is the gate discriminating rather
than failing on anything hard.

---

## Likely questions

**"Is the LLM looking at the video?"** No. It receives measurements as JSON and writes prose; no
frame ever reaches it. The seeing is MediaPipe and OpenCV.

**"Why not use a VLM for the vision?"** Not a cost argument — run `scripts/cost_model.py` live. At
four downscaled frames a VLM is *cheaper* than what we ship ($0.0198 vs $0.0275). It loses on
capability: no per-landmark visibility score (the signal every `cannot_assess` rests on), no
pixel-level joint location, no bar path across 236 frames, and nothing a human can check against
the frame. Give it enough frames to do those things and it costs $0.67 a video — 24× ours — and
still returns estimates rather than measurements.

**"What about running it on the edge — Jetson?"** That is the strongest version of the question and
I would take it for a gym-installed unit: zero marginal cost, no upload latency, and no footage of
someone's body leaving the premises. I would swap MediaPipe for Meta's Sapiens (better on occluded
joints, which is our weak spot) and run narration locally. The architecture is unchanged — a
specialist model measures, a language model explains.

**"What if the model is wrong?"** It cannot be wrong about measurements — it does not make them.
It can only be wrong about wording or judgment, and it is barred in code from making any verdict
more confident than the rule engine's. `agent_note` records every rejected attempt.

**"Is 65 seconds acceptable?"** For asynchronous form review, yes. The fix is known: run plate
detection every N frames and track between them, which is most of the 45s that per-frame Hough
costs.

**"How do I add a criterion?"** Add it to the YAML with an id, source pages, a verbatim quote, an
assessability level, and a measure the vision layer implements. The loader validates it at boot and
reports unmapped measures.

**"What would you do next?"** A labelled clip set, so tolerances stop being judgement calls. It is
the one thing this build could not do inside the time box, and it gates everything else.
