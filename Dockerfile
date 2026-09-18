# Backend container. Runs unchanged on Hugging Face Spaces, Google Cloud Run, Render or Fly.
#
# Build context is the repository root, because the container has to mirror the repo layout:
# the skill loader resolves the skill directory three parents up from
# backend/app/skill/loader.py, and the pose model two parents up from backend/app/vision/pose.py.
# Flattening the tree would break both.
#
# Hugging Face Spaces expects port 7860; Cloud Run injects $PORT. The CMD honours $PORT and
# falls back to 7860, so one image suits both.

FROM python:3.12-slim

# ffprobe is not optional: the upload gate shells out to it before any compute is spent.
#
# The graphics libraries are not optional either, which is not obvious. MediaPipe links against
# EGL and GLES even when every calculator runs on the CPU, so a slim image fails at the first
# frame with `OSError: libEGL.so.1: cannot open shared object file`. The health endpoint answers
# perfectly well without them, so this only shows up once a video is actually analysed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libegl1 \
        libgles2 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY backend/requirements.txt backend/requirements.txt

# opencv-python-headless instead of opencv-contrib-python. This project uses only VideoCapture,
# cvtColor, medianBlur, HoughCircles, resize and the drawing calls, none of which are
# contrib-only, and headless drops the GUI dependencies a server will never use. Saves ~75 MB.
RUN sed -i 's/^opencv-contrib-python.*/opencv-python-headless/' backend/requirements.txt \
    && pip install --no-cache-dir -r backend/requirements.txt

# Bake the pose model in so a cold start does not fetch 29 MB before it can answer.
RUN python -c "import urllib.request, pathlib; \
d = pathlib.Path('/srv/backend/models'); d.mkdir(parents=True, exist_ok=True); \
urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task', d / 'pose_landmarker_heavy.task')"

COPY backend/app backend/app
COPY skill skill

# Writable scratch. Container filesystems are ephemeral, so jobs do not survive a restart. That
# is the same limitation as the local build and is documented in BUILD_NOTES.
RUN mkdir -p backend/storage/uploads backend/storage/artifacts

ENV PYTHONPATH=/srv/backend \
    PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
