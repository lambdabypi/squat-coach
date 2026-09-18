# Squat Coach — Tech Stack & File Structure Plan

Working plan for the Novulis AI Engineer assignment. Clock and budget live in [TIMELOG.md](TIMELOG.md).

Product name: **Squat Coach**. Repo root: `squat-coach/`.

---

## 1. The shape of the problem

The reference document (*Starting Strength*, "The Squat", ref pp. 1–35) ends on page 35 with an
explicit checklist — *The Important Things You're Going to Do Wrong*: **Depth, Knee position,
Stance, Eye gaze, Back angle, Hip drive, Bar placement, Rack height**. That list is the spine of
the agent skill. Everything else in the chapter is supporting rationale and citation material.

The decisive engineering fact: **a side view can only see some of those eight.** Stance width and
knees-out are front-plane properties. Rack height is usually out of frame. An honest system says
`cannot_assess` for those, and the brief rewards that over invented precision. So the coverage
table is a first-class deliverable, not a footnote.

The second decisive fact: **the document states almost no numbers.** It gives geometry ("hip
crease below the top of the patella"), a couple of loose figures (toes ~30°, back ~45°, eyes 4–5 ft
ahead, heels shoulder-width), and nothing else. Every threshold the system uses is therefore tagged
with provenance — `document_stated` or `engineering_tolerance` — and the UI renders them
differently. This directly answers *"do not add unsupported thresholds and present them as document
requirements."*

---

## 2. Stack

| Layer | Choice | Why this, in a 5-hour box |
|---|---|---|
| Pose | **MediaPipe Pose Landmarker** (`heavy` .task), Python | 33 landmarks **with per-landmark `visibility`** — that score is what powers observed-vs-estimated and `cannot_assess`. Verified: mediapipe 1.0.1 has a py3.13 win_amd64 wheel, no second interpreter needed. |
| Bar tracking | **OpenCV** — HoughCircles on the plate, seeded from the shoulder landmark, handed to a CSRT tracker | The plate is a large high-contrast circle in a side view; this is a genuine *observation* of the bar, not a shoulder-offset guess. Falls back to the shoulder proxy, labelled `estimated`. |
| Video I/O | **OpenCV VideoCapture** + **ffmpeg/ffprobe** (already installed) | ffprobe gates the upload (duration, fps, rotation, resolution) before we spend compute. |
| Backend | **FastAPI** + Pydantic v2, Python 3.13 | Same process owns the CV, the skill and the agent. Pydantic models are the contract between geometry and LLM and frontend. |
| Agent | **Claude** via the Anthropic Python SDK, tool-use + structured output | Geometry is computed in code and handed to the model as evidence; the model does judgment, grounding and phrasing. It never measures. *(Shipped as `claude-haiku-4-5`; the planned prompt caching turned out not to apply at this prompt size — see BUILD_NOTES.)* |
| Frontend | **Next.js 15 (App Router) + TypeScript + Tailwind** | UI only — no API keys, no CV. `<video>` + `<canvas>` overlay is the fastest path to a synchronized annotated player. |
| Job state | In-memory dict + polling `GET /jobs/{id}` | A queue is not the point of this exercise. Documented as a known limitation. |

### Architectural call: two services, all AI in the backend

Browser talks to FastAPI directly (CORS-allowed) for upload, status and artifacts, and to FastAPI
for the assessment too. **Next.js holds no secrets and does no inference.** The skill, the rule
engine and the Claude client live together in one Python package, so "edit the skill, rerun, see
the assessment change" — which they will ask for live — is a single-service operation.

### Rejected alternatives

- **Browser-only with `@mediapipe/tasks-vision` WASM.** Tempting: zero backend, zero upload. But
  bar tracking in JS would collapse to a shoulder-offset estimate, and bar path over the midfoot is
  a named requirement. OpenCV's circle detection is worth the backend.
- **Python 3.12 venv.** Was the plan until the 1.0.1 wheel check came back clean. Skipped.
- **Re-encoding an annotated MP4 as the primary artifact.** It's the *fallback*, not the primary —
  the canvas overlay is instant and the brief accepts "synchronized video overlays". MP4 render
  stays as a download for the evidence pack, and is cut list item #1.
- **YOLO-pose / ultralytics.** Heavier install, and no per-landmark visibility score, which is the
  one signal the honesty requirements depend on.

---

## 3. The skill

Separate, inspectable, editable without touching app code. Two files, one source of truth.

`skill/squat_standards.yaml` — machine-readable, loaded and validated by Pydantic at startup:

```yaml
- id: depth
  name: Squat depth
  source:
    pages: [2, 18, 35]
    figures: ["2-1", "2-10"]
    quote: >
      Correctly is deep, with hips dropping below level with the top of the patellas.
      Correctly is therefore full range of motion.
  assessable_from_side_view: full
  requires_landmarks: [left_hip, right_hip, left_knee, right_knee]
  measure: hip_crease_y_minus_patella_top_y_at_bottom
  rule:
    meets_when: "hip_y > knee_y"          # image coords, y grows downward
    provenance: document_stated            # geometric, not numeric — no invented margin
  tolerance:
    value_px_normalized: 0.02
    provenance: engineering_tolerance      # landmark jitter, NOT a document requirement
  uncertainty:
    cannot_assess_when:
      - "min_visibility(required_landmarks) < 0.6 at bottom frame"
      - "camera_plane != sagittal"
  feedback_on_fail: >
    Stop short of depth and it is a partial squat ... check stance width, toe angle and
    whether the knees are being shoved out. (ref p.32)
```

`skill/SKILL.md` — the same rules in prose, for a human reviewer to read in 3 minutes.
`skill/coverage.md` — the table below, which is also served to the UI.
`skill/CITATIONS.md` — criterion → reference page index.

### Coverage: what a side view can and cannot judge

| Criterion | Ref pages | Side view | How it's measured / why not |
|---|---|---|---|
| Depth | 2, 18, 35 | **Full** | Hip landmark below knee landmark at the bottom frame |
| Back angle (~45°, not vertical, held constant) | 10, 27, 31, 35 | **Full** | Shoulder→hip vector vs horizontal, per frame |
| Bar path over midfoot | 7–9, 13, 31 | **Full** | Tracked bar x vs midfoot x, normalized by shin length |
| Hip drive (hips rise before chest) | 28, 35 | **Full** | Hip vs shoulder vertical velocity, first 150 ms of ascent |
| Knees slightly forward of toes at bottom | 27 | **Full** | Knee x vs toe x at bottom frame |
| Heels flat on the floor | 27 | **Partial** | Heel landmark stability; low confidence if the foot is occluded |
| Bar placement (low-bar, below scapular spine) | 21, 35 | **Partial** | Bar y vs shoulder landmark — coarse; ~2 cm decides it and we cannot resolve that |
| Eye gaze (down, 4–5 ft ahead) | 29–30, 35 | **Partial** | Nose/ear pitch proxy; reported with explicit low confidence |
| Knee position (knees shoved out) | 19, 27, 32, 35 | **None** | Frontal-plane property. Invisible in the sagittal view. Needs a front camera. |
| Stance width & toe angle (~30°) | 24, 35 | **None** | Frontal/transverse plane. Invisible in the sagittal view. |
| Rack height / step-back procedure | 20–22, 35 | **None** | Almost always outside the frame; not a rep-level property |

Three of the document's own eight headline criteria are structurally unassessable from the
required input. That is a finding, and the UI states it up front rather than burying it.

---

## 4. Pipeline

```
upload ──▶ probe ──▶ pose ──▶ smooth ──▶ reps ──▶ metrics ──▶ bar ──▶ quality
                                                                        │
                                              ┌─────────────────────────┘
                                              ▼
                                       rule engine (deterministic)
                                              │   candidate findings + evidence
                                              ▼
                                       Claude (judgment + grounding)
                                              │   validated Report
                                              ▼
                              overlay.json  +  annotated.mp4  +  report.json
```

Stage notes:

- **probe** — ffprobe. Rejects early with a real reason: unsupported codec, > 60 s, < 15 fps,
  rotation metadata. Reasons surface verbatim in the UI.
- **reps** — hip-y signal → Savitzky-Golay smoothing → prominence-filtered local maxima are the
  bottoms; velocity zero-crossings give descent/ascent boundaries. Under 2 detected reps the job
  still reports, flagged low confidence.
- **quality** — the honesty gate. Sagittal-view check (shoulder/hip left-right landmark separation
  ratio), per-frame occlusion, framing (feet and bar in frame), tracking continuity. Its output
  decides which criteria are even eligible for a verdict.
- **Units** — every distance is normalized by shin length (ankle→knee) so findings are
  scale-invariant and comparable across videos. Angles are in degrees.

### Where the LLM is and is not

**Is:** deciding meets / does not meet / cannot assess given the evidence and rule; writing the
explanation and the actionable coaching line; choosing which citation supports the call; stating
the uncertainty that qualifies the conclusion.

**Is not:** measuring anything. Every number in the report comes from `vision/metrics.py`. The
model receives a compact evidence JSON per rep and the relevant skill rules, and returns findings
through a tool schema that Pydantic validates. If validation fails, one repair round-trip; if it
fails again, the deterministic rule-engine verdict ships with a note that the narration was
unavailable. **The system degrades to something true rather than something fluent.**

---

## 5. File structure

```
squat-coach/
├── README.md                     # what it is, setup, env var NAMES, how to run
├── BUILD_NOTES.md                # architecture, model/tool choices, actual time, cost, trade-offs, limits
├── AI_USAGE.md                   # delegated / inspected / the one real mistake caught
├── TIMELOG.md
├── .env.example                  # ANTHROPIC_API_KEY=  (name only, never a value)
├── .gitignore                    # storage/, .env, *.mp4, models/
│
├── skill/                        # ── the agent skill: separate, inspectable, editable
│   ├── SKILL.md
│   ├── squat_standards.yaml
│   ├── coverage.md
│   └── CITATIONS.md
│
├── backend/
│   ├── requirements.txt
│   ├── models/                   # pose_landmarker_heavy.task (downloaded, gitignored)
│   ├── storage/                  # uploads + artifacts (gitignored)
│   └── app/
│       ├── main.py               # FastAPI app, CORS, static artifacts
│       ├── config.py             # settings, limits, env var names
│       ├── models.py             # Pydantic: Job, Rep, Evidence, Finding, Report, Coverage
│       ├── jobs.py               # in-memory store, stage + percent progress, failure reasons
│       ├── pipeline.py           # orchestrates probe→pose→…→agent, emits progress
│       ├── api/
│       │   ├── videos.py         # POST /videos (multipart, validated)
│       │   ├── jobs.py           # GET /jobs/{id}  → stage, pct, error
│       │   └── reports.py        # GET /jobs/{id}/report | /overlay | /annotated.mp4
│       ├── vision/
│       │   ├── probe.py          # ffprobe gate: codec, duration, fps, rotation, size
│       │   ├── pose.py           # MediaPipe landmarks + visibility, per frame
│       │   ├── smoothing.py      # Savitzky-Golay, shin-length normalization
│       │   ├── reps.py           # segmentation, bottom frame per rep
│       │   ├── bar.py            # HoughCircles seed → CSRT track → bar path
│       │   ├── metrics.py        # depth, back angle, bar deviation, hip drive, knee/toe
│       │   ├── quality.py        # sagittal check, occlusion, framing, tracking continuity
│       │   └── render.py         # annotated MP4 (skeleton, bar path, angles, rep labels)
│       ├── skill/
│       │   ├── loader.py         # YAML → validated Criterion models
│       │   └── rules.py          # deterministic pass → candidate findings + evidence
│       └── agent/
│           ├── client.py         # Anthropic client, prompt caching, retry
│           ├── prompts.py        # system prompt, evidence framing, refusal-to-invent rules
│           ├── tools.py          # submit_findings / get_criterion / get_rep_evidence
│           └── assess.py         # per-rep evaluation → summary → validated Report
│
├── frontend/
│   ├── package.json
│   ├── app/
│   │   ├── page.tsx                    # upload + recording requirements
│   │   ├── analyze/[jobId]/page.tsx    # staged progress, honest failure states
│   │   └── report/[jobId]/page.tsx     # player + findings + coverage
│   ├── components/
│   │   ├── Uploader.tsx                # drag-drop, client-side pre-checks, upload %
│   │   ├── RequirementsCard.tsx        # formats, duration, framing, side-view rules
│   │   ├── ProgressStages.tsx
│   │   ├── VideoWithOverlay.tsx        # <video> + <canvas>, rAF-synced to currentTime
│   │   ├── RepTimeline.tsx             # scrub to any rep's bottom frame
│   │   ├── FindingCard.tsx             # verdict · measurement · timestamp jump · citation · uncertainty
│   │   ├── CitationPopover.tsx         # the quoted source text, inline
│   │   └── CoverageTable.tsx           # what a side view cannot judge, stated up front
│   └── lib/
│       ├── api.ts
│       ├── types.ts                    # mirrors backend Pydantic models
│       └── draw.ts                     # skeleton, bar path, angle arcs on canvas
│
├── scripts/
│   ├── fetch_sample.py           # yt-dlp the common sample (youtube.com/shorts/TRvg083BrXY)
│   └── run_cli.py                # headless video → report.json, for evidence + debugging
│
└── EVIDENCE/
    ├── common-sample/            # report.json, annotated frames, verification notes
    └── hard-sample/              # a deliberately difficult/unsuitable recording + what broke
```

`scripts/run_cli.py` exists from block 3 onward. Every vision stage is verifiable headlessly
before a single line of UI is written — that's what keeps the back half of the budget safe.

---

## 6. Key data contract

One `Finding` per (rep × criterion). This shape is what the brief asks for, field by field:

```python
class Finding(BaseModel):
    rep_index: int
    criterion_id: str
    criterion_name: str
    source: SourceRef            # pages, figure, verbatim quote
    verdict: Literal["meets_standard", "does_not_meet_standard", "cannot_assess"]
    timestamp_s: float           # jumps the player here
    frame_index: int
    measurement: Measurement | None   # value, unit, + observed vs estimated
    threshold: Threshold | None       # value + document_stated | engineering_tolerance
    explanation: str
    feedback: str | None              # grounded in the document
    uncertainty: str | None           # what qualifies this conclusion
    confidence: Literal["high", "medium", "low"]
```

`Measurement.basis` is the field that makes the whole thing defensible: `observed` (tracked pixels)
vs `estimated` (derived or inferred). The UI renders estimates in a visibly different weight, and a
`cannot_assess` verdict shows the reason instead of a number.

---

## 7. Cost & latency estimate (to be measured, not guessed, in block 8)

> **Measured afterwards — these estimates were wrong.** Actual: ~60s vision, ~25–33s agent,
> $0.0275 per video on `claude-haiku-4-5`, and the skill block does not cache at this size.
> See BUILD_NOTES for the corrections. Left unedited below as the original plan.

| | Estimate |
|---|---|
| Pose + CV, 15 s clip @ 30 fps | ~20–40 s CPU |
| MP4 render | ~10–15 s |
| Claude input | ~15–25k tokens (skill block cached across reps) |
| Claude output | ~3–5k tokens |
| **Per video** | **a few cents; well under $0.10** |

BUILD_NOTES will carry the measured numbers from the actual evidence runs.

---

## 8. Known limitations to state honestly in BUILD_NOTES

- 2D monocular pose. No true 3D joint centres, no depth — the hip-crease landmark is MediaPipe's
  hip *centre*, not the crease the document describes. Stated as a systematic bias, not hidden.
- Three of the document's eight headline criteria are unassessable from the required input.
- In-memory job store; a restart loses jobs. No auth, no persistence, no queue.
- Bar detection assumes a visible plate. Bumper-free bars, cluttered racks and dark gyms degrade to
  the shoulder-proxy estimate, which is labelled as such.
- Rep segmentation assumes a continuous set in frame; walk-outs and re-racks can produce phantom reps.
- Thresholds not present in the document are engineering tolerances and are labelled everywhere.

---

## Immediate next step

Block 1 (20 min): `squat-coach/` scaffold, `pip install fastapi uvicorn mediapipe opencv-contrib-python
scipy pydantic anthropic pyyaml python-multipart yt-dlp`, download the pose model, fetch the common
sample, and smoke-test landmarks + HoughCircles on a single extracted frame. Nothing else gets
built until pose and plate detection are proven on that one frame.
