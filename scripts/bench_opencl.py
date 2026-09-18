"""Does OpenCL (OpenCV T-API) accelerate the barbell detection path on this GPU?

MediaPipe's GPU delegate is Linux-only and the pip OpenCV wheel has no CUDA, so neither of the
obvious GPU routes is open on a Windows laptop. OpenCL is a third route: OpenCV's T-API runs the
same calls on the GPU when the inputs are UMat instead of ndarray, and this machine reports
OpenCL through NVD3D11.

HoughCircles is 51% of the analysis time, so if the GPU can take it, that is the whole win.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def frames(video: Path, limit: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    out = []
    while len(out) < limit:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out


def cpu_pass(imgs: list[np.ndarray], min_r: int, max_r: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    hits = 0
    for f in imgs:
        g = cv2.medianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), 5)
        c = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=200,
                             param1=120, param2=55, minRadius=min_r, maxRadius=max_r)
        hits += c is not None
    return time.perf_counter() - t0, hits


def ocl_pass(imgs: list[np.ndarray], min_r: int, max_r: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    hits = 0
    for f in imgs:
        u = cv2.UMat(f)
        g = cv2.medianBlur(cv2.cvtColor(u, cv2.COLOR_BGR2GRAY), 5)
        c = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=200,
                             param1=120, param2=55, minRadius=min_r, maxRadius=max_r)
        arr = c.get() if isinstance(c, cv2.UMat) else c
        hits += arr is not None and len(arr) > 0
    return time.perf_counter() - t0, hits


def main() -> int:
    video = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    print(f"OpenCL available : {cv2.ocl.haveOpenCL()}")
    cv2.ocl.setUseOpenCL(True)
    print(f"OpenCL enabled   : {cv2.ocl.useOpenCL()}")
    try:
        d = cv2.ocl.Device_getDefault()
        print(f"device           : {d.name()} ({d.vendorName()})")
        print(f"compute units    : {d.maxComputeUnits()}, global mem "
              f"{d.globalMemSize() / 1e9:.1f} GB")
    except Exception as exc:
        print(f"device           : unavailable ({exc})")

    imgs = frames(video, n)
    h, w = imgs[0].shape[:2]
    short = min(w, h)
    min_r, max_r = int(0.12 * short), int(0.25 * short)
    print(f"\n{len(imgs)} frames at {w}x{h}, radius band {min_r}-{max_r}px\n")

    cv2.ocl.setUseOpenCL(False)
    t_cpu, hits_cpu = cpu_pass(imgs, min_r, max_r)

    cv2.ocl.setUseOpenCL(True)
    t_ocl, hits_ocl = ocl_pass(imgs, min_r, max_r)
    # A second pass: the first includes OpenCL kernel compilation, which is a one-off.
    t_ocl2, _ = ocl_pass(imgs, min_r, max_r)

    print(f"{'path':28s} {'seconds':>9s} {'ms/frame':>10s} {'detections':>11s}")
    print("-" * 62)
    print(f"{'CPU':28s} {t_cpu:9.2f} {t_cpu / len(imgs) * 1000:10.1f} {hits_cpu:11d}")
    print(f"{'OpenCL (first pass)':28s} {t_ocl:9.2f} {t_ocl / len(imgs) * 1000:10.1f} {hits_ocl:11d}")
    print(f"{'OpenCL (warm)':28s} {t_ocl2:9.2f} {t_ocl2 / len(imgs) * 1000:10.1f} {hits_ocl:11d}")
    print()
    if t_ocl2 < t_cpu:
        print(f"OpenCL is {t_cpu / t_ocl2:.2f}x faster once warm")
    else:
        print(f"OpenCL is {t_ocl2 / t_cpu:.2f}x SLOWER than CPU here")
        print("Not unusual: HoughCircles has a sequential accumulator stage, and moving each")
        print("frame to and from the GPU costs more than the parallel part saves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
