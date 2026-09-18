# Deploying

The frontend and backend deploy separately, because they have different shapes: the frontend is
static-plus-edge and the backend is a long-running container that needs `ffmpeg`, roughly 400 MB
of Python wheels and a minute of CPU per video.

Everything here works on free tiers. See [FUTURE_SPEC.md](FUTURE_SPEC.md) section 7b for why the
backend cannot go on Vercel.

---

## Backend: container

One image, `Dockerfile` at the repository root, build context the root. It mirrors the repo
layout because the skill loader and the pose model resolve paths relative to it.

```bash
docker build -t squat-coach-backend .
docker run -p 7860:7860 squat-coach-backend
curl localhost:7860/health
python scripts/e2e_test.py EVIDENCE/common-sample/common_sample.mp4 http://localhost:7860
```

Run the last line, not just the health check. The health endpoint answers happily from an image
that cannot analyse a single frame: MediaPipe links against EGL and GLES even when every
calculator runs on the CPU, so `python:3.12-slim` fails at the first frame with
`OSError: libEGL.so.1: cannot open shared object file`. The Dockerfile installs `libegl1`,
`libgles2`, `libgl1`, `libglib2.0-0` and `libgomp1` for that reason. A container that passes
`/health` and fails on upload is the easy mistake here.

The image also bakes in the 29 MB pose model so cold starts do not fetch it, installs `ffmpeg` for
the upload gate, and swaps `opencv-contrib-python` for `opencv-python-headless` (about 75 MB
smaller; this project uses no contrib-only calls). It listens on `$PORT`, defaulting to 7860.
Built size is roughly 2 GB, which is fine for a container host and is the reason this cannot be a
Vercel function.

### Option A: Hugging Face Spaces (no card required) - recommended

The most genuinely free option, and the right audience.

**Activate the project venv first.** Both `hf` and `huggingface_hub` install into it, not onto the
system PATH, so without this you get `hf: not recognized` and then `ModuleNotFoundError`:

```powershell
.\backend\.venv\Scripts\Activate.ps1     # Windows PowerShell
source backend/.venv/bin/activate        # macOS / Linux
```

Then two commands:

```bash
hf auth login                                   # once; or set HF_TOKEN
python scripts/deploy_hf.py --name squat-coach-api
```

The token needs **write** permission; a read token cannot create a Space. Create one at
https://huggingface.co/settings/tokens.

The script creates the Space as a Docker Space, writes the YAML frontmatter Hugging Face needs,
and uploads only what the container requires: the Dockerfile, `backend/app`, `skill/` and the
requirements. Not the frontend, not `EVIDENCE`, not the venv. Run it with `--dry-run` first to see
the file list.

It deliberately does not upload `ANTHROPIC_API_KEY`. Set that in the Space settings yourself if
you want agent narration on a public URL, and read the warning below first.

Spaces serve on port 7860, which the Dockerfile already defaults to. After the first build, set
`ALLOWED_ORIGINS` in the Space variables to your frontend URL.

Free Spaces sleep when idle and take a moment to wake. For a demo, open it a minute early.

### Option B: Google Cloud Run

Always-free allowance of roughly 2M requests and 360k vCPU-seconds per month, scales to zero.
**Billing must be enabled on the project even to use the free tier**, so confirm which project you
are deploying into before running this.

```bash
gcloud config set project YOUR_PROJECT
gcloud run deploy squat-coach-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars ALLOWED_ORIGINS=https://YOUR-FRONTEND.vercel.app
```

`--source .` builds with Cloud Build, so no local Docker is needed. Give it 2 vCPU: analysis is
CPU-bound and a single core roughly doubles the wall time.

### Option C: Render or Fly.io

Both take the same Dockerfile. The generous legacy free tiers are closed to new accounts, so check
what is currently offered before relying on either.

---

## Frontend: Vercel

```bash
cd frontend
vercel login
vercel --prod
```

Set one environment variable in the Vercel project:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | the backend URL, for example `https://your-space.hf.space` |

Then set `ALLOWED_ORIGINS` on the backend to the Vercel URL, so CORS allows it. Getting this wrong
produces a bare "Failed to fetch" in the browser with a perfectly healthy backend; see
`app/config.py` for why an empty value is treated as unset.

---

## Running the deployment without an API key

The public demo is deliberately deployed **without** `ANTHROPIC_API_KEY`.

A public URL with no authentication in front of it means anyone who finds it can spend your API
credit, at roughly $0.026 per video. The application is built for this: without a key, the
deterministic rule engine produces every verdict, measurement, citation and uncertainty note
itself. Only the narration wording is plainer, and the interface says so.

If you want full agent narration on a live demo, set the key and take the deployment down
afterwards, or put a shared secret in front of `POST /videos`.

---

## What does not survive deployment

Stated so it is not discovered during a review:

- **Jobs are in memory.** A restart, a scale-to-zero, or a second instance loses in-flight work.
  Fine for a single-user demo, wrong for production. Fixing it means object storage plus a queue.
- **Uploads are ephemeral.** The container filesystem is wiped on restart, so a report cannot be
  reopened later.
- **One instance assumed.** Polling for job status expects to reach the instance that started the
  job, so keep max instances at 1 or add shared state.
- **Free tiers sleep.** First request after idle pays a cold start, including MediaPipe import.
