"""Match thread pools to the container's actual CPU allowance.

The deployed service ran at 0.41 frames per second where the same image manages 4.1 locally, and
raising the vCPU allocation from 2 to 4 made it *slower*. That pattern is the signature of thread
oversubscription, not of slow hardware.

The cause: OpenCV and TFLite size their thread pools from the number of CPUs the machine reports,
and inside a container that is the number of cores on the *host*, not the quota the cgroup will
actually let you use. On a host with many cores and a 2 vCPU quota, OpenCV happily starts dozens
of worker threads that then fight over two cores' worth of time slices. Every extra thread adds
context switching and cache pressure while the available work stays the same, which is exactly
why more vCPU produced less throughput: a larger quota does not shrink the thread pool.

`os.cpu_count()` does not help here, because it reports host cores too. The quota lives in the
cgroup filesystem, so read it there and size the pools to match.
"""

from __future__ import annotations

import os
from pathlib import Path

CGROUP_V2_MAX = Path("/sys/fs/cgroup/cpu.max")
CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def cgroup_cpu_quota() -> float | None:
    """CPUs this container may actually use, or None if unlimited or not in a cgroup."""
    try:
        if CGROUP_V2_MAX.exists():
            quota, period = CGROUP_V2_MAX.read_text().split()
            if quota == "max":
                return None
            return int(quota) / int(period)
        if CGROUP_V1_QUOTA.exists() and CGROUP_V1_PERIOD.exists():
            quota = int(CGROUP_V1_QUOTA.read_text().strip())
            if quota <= 0:
                return None
            return quota / int(CGROUP_V1_PERIOD.read_text().strip())
    except (OSError, ValueError):
        return None
    return None


def effective_cpus() -> int:
    """How many threads it makes sense to run, never fewer than one."""
    quota = cgroup_cpu_quota()
    if quota is not None:
        return max(1, int(quota))
    return max(1, os.cpu_count() or 1)


def describe() -> dict:
    """Diagnostics, so a future slowdown can be checked rather than guessed at."""
    import cv2

    return {
        "os_cpu_count": os.cpu_count(),
        "cgroup_quota": cgroup_cpu_quota(),
        "effective_cpus": effective_cpus(),
        "opencv_threads": cv2.getNumThreads(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
    }


def configure() -> dict:
    """Size the thread pools to the quota. Call once, before any heavy work.

    Returns the before/after picture for logging.
    """
    import cv2

    n = effective_cpus()
    before = cv2.getNumThreads()

    # OpenCV parallelises HoughCircles and the colour conversions.
    cv2.setNumThreads(n)

    # OpenMP backs several numeric libraries in this stack. Setting it after they are imported
    # is unreliable, so the Dockerfile also sets it in the environment; this is the fallback for
    # running outside the image.
    os.environ.setdefault("OMP_NUM_THREADS", str(n))

    return {"effective_cpus": n, "opencv_threads_before": before,
            "opencv_threads_after": cv2.getNumThreads()}
