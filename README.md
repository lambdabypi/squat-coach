# Squat Coach

Upload a side-view barbell squat. Squat Coach tracks the hips, knees, ankles and the barbell,
segments the set into repetitions, and assesses each one against *The Squat* chapter of
*Starting Strength* — citing the page behind every verdict, and saying plainly which criteria a
side view cannot judge at all.

The reference document is not baked into the application. It lives in [`skill/`](skill/) as an
inspectable, editable set of rules. Change a rule there and the assessment changes, with no
application code touched.

---

## What it does

1. **Gates the upload** — codec, duration, frame rate, resolution — and rejects with a reason you
   can act on, before spending any compute.
2. **Tracks the movement** in a single decode pass: MediaPipe pose landmarks plus OpenCV barbell
   plate detection.
3. **Finds repetitions** from the hip-height signal and locates each bottom position.
4. **Runs quality gates** that decide what the footage is capable of supporting.
5. **Measures** depth, back angle, bar path, hip drive and knee position in code.
6. **Assesses** each repetition with Claude, which judges, grounds and phrases — but never
   measures.
7. **Shows the evidence**: a canvas overlay synchronised to the video, with every finding linked
   to the timestamp it came from.

---

## Quick start

Prerequisites: **Python 3.11+**, **Node 20+**, **ffmpeg** on `PATH`.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python ../scripts/fetch_model.py          # downloads pose_landmarker_heavy.task (~31 MB)

export ANTHROPIC_API_KEY=...              # optional; see "Running without a key" below
export PYTHONPATH=$PWD
uvicorn app.main:app --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

### Environment variables

Names only — no values are committed. See [`.env.example`](.env.example).

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | no | Enables the agent stage. Without it the deterministic rule engine runs alone. |
| `ALLOWED_ORIGINS` | no | CORS origins for the API. Defaults to `http://localhost:3000`. |
| `NEXT_PUBLIC_API_URL` | no | Backend URL the browser calls. Defaults to `http://localhost:8000`. |

### Running without a key

The application is fully functional without `ANTHROPIC_API_KEY`. Every verdict, measurement,
citation and uncertainty note comes from the deterministic rule engine; the agent only improves
the wording and writes the overall summary. Without a key the UI says so, and the findings are
plainer but identical in substance. This is also the degradation path if the API call fails.

---

## Headless use

Same code as the API, no UI, no key needed:

```bash
python scripts/run_cli.py path/to/video.mp4 --out ./out --no-agent
```

Writes `report.json` and `overlay.json`, and prints a per-repetition table. This is how the
evidence in [`EVIDENCE/`](EVIDENCE/) was produced.

Other scripts:

| Script | Purpose |
|---|---|
| `scripts/fetch_model.py` | Download the pose model. |
| `scripts/fetch_sample.py` | Download the assignment's common sample video. |
| `scripts/e2e_test.py` | Upload → poll → report against a running API. |
| `scripts/test_vision.py` | Vision core only: pose, bar, reps, view geometry. |
| `scripts/gen_skill_docs.py` | Regenerate `skill/coverage.md` and `skill/CITATIONS.md`. |
| `scripts/check_video_serving.py` | Confirm byte-range streaming works. |

---

## Editing the skill

```bash
cd backend
python -m app.skill.loader      # validates and prints every criterion with its provenance
```

The loader refuses to start on a malformed skill, so a bad edit is an error rather than a silent
behaviour change. See [`skill/SKILL.md`](skill/SKILL.md).

The rule most worth knowing: every threshold is tagged `document_stated` or
`engineering_tolerance`. The reference document states almost no numbers, so anything numeric that
is not in the text is ours, is labelled as ours, and is never presented to a user as a requirement
from the book.

---

## Layout

```
skill/            the document-derived standard — rules, coverage, citations
backend/app/
  vision/         probe, pose, bar, smoothing, reps, metrics, quality
  skill/          loader (validation) and rules (deterministic verdicts)
  agent/          prompts, tool schema, validated assessment
  pipeline.py     orchestration
  main.py         FastAPI
frontend/         Next.js UI — no secrets, no inference
EVIDENCE/         runs on the common sample and two difficult recordings
scripts/          headless tools
```

---

## Known limitations

Stated at greater length in [`BUILD_NOTES.md`](BUILD_NOTES.md):

- 2D monocular pose. The document's depth landmark is the hip **crease**; the model gives a hip
  **joint centre**, which sits higher and biases depth toward "not deep enough".
- Three of the document's eight headline criteria — knees-out, stance, rack height — cannot be
  assessed from a side view at all.
- In-memory job store: a restart loses jobs, and it does not survive more than one process.
- Bar detection assumes a visible plate. Without one it falls back to a shoulder-offset estimate,
  labelled `estimated` everywhere it is used.
- No authentication, no persistence, no queue.
