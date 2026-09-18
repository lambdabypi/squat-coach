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

# Install requirements exactly as pinned. No substitutions.
#
# Two earlier attempts to swap opencv-contrib-python for the smaller opencv-python-headless are
# worth recording, because the second failure is not obvious:
#
#   1. The first swap dropped the version pin along with the package name, resolving to OpenCV
#      5.0 against the 4.12 this build was verified on. That silently flipped a verdict on the
#      common sample: back angle went from meets_standard to does_not_meet_standard.
#
#   2. Pinning the headless package did not fix it either, because mediapipe 1.0.1 declares
#      opencv-contrib-python as its own dependency, unpinned. pip honoured the headless pin AND
#      pulled contrib 5.0.0.93 to satisfy mediapipe. Both install into the same `cv2` namespace,
#      contrib shadowed headless, and the image ran OpenCV 5 while claiming 4.12. It also
#      carried both wheels, 54 MB plus 82 MB, so the saving the swap existed for was negative.
#
# Keeping the pin on opencv-contrib-python satisfies mediapipe at the verified version and
# installs one copy. The image is larger than the headless ideal and correct, which is the right
# side of that trade.
RUN grep -E '^opencv' backend/requirements.txt \
    && pip install --no-cache-dir -r backend/requirements.txt \
    && python -c "import cv2, sys; v = cv2.__version__; \
print('opencv in image:', v); \
sys.exit(0 if v.startswith('4.12') else 'expected OpenCV 4.12, got ' + v)"

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
    PYTHONUNBUFFERED=1 \
    # Thread pools must be sized before the numeric libraries load, so set them here as well as
    # in app/cpu.py. OpenCV and TFLite otherwise size their pools from the HOST's core count,
    # which inside a 2 vCPU cgroup means dozens of threads contending over two cores' worth of
    # time. That is what made the deployed service 10x slower than the same image locally, and
    # why raising the vCPU allocation made it slower rather than faster.
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 \
    VECLIB_MAXIMUM_THREADS=2

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
