"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Overlay } from "@/lib/types";

export interface PlayerHandle {
  seek: (t: number) => void;
}

interface Props {
  src: string;
  overlay: Overlay;
  highlightFrame?: number | null;
}

const COL = {
  observed: "#3fb950",
  low: "#f0883e",
  bone: "#58a6ff",
  bar: "#ffd166",
  barEst: "#8b949e",
  path: "rgba(255,209,102,.85)",
  pathEst: "rgba(139,148,158,.6)",
};

/**
 * Canvas overlay synchronised to <video>.currentTime.
 *
 * We draw on top of the original file rather than re-encoding an annotated MP4: the result is
 * available the instant analysis finishes, it stays sharp at any size, and it is scrubbable.
 * The brief accepts "playable annotated video or synchronized video overlays".
 */
const VideoWithOverlay = forwardRef<PlayerHandle, Props>(function VideoWithOverlay(
  { src, overlay, highlightFrame },
  ref,
) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [showBarPath, setShowBarPath] = useState(true);
  const [t, setT] = useState(0);

  useImperativeHandle(ref, () => ({
    seek: (time: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = Math.max(0, Math.min(time, overlay.duration_s - 0.01));
      v.pause();
    },
  }));

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = overlay.width;
    canvas.height = overlay.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const time = video.currentTime;
      setT(time);
      const i = Math.min(
        overlay.frames.length - 1,
        Math.max(0, Math.round(time * overlay.fps)),
      );
      const f = overlay.frames[i];
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (f) {
        if (showSkeleton) {
          // Bones first, joints on top.
          ctx.lineWidth = Math.max(3, overlay.width * 0.005);
          ctx.strokeStyle = COL.bone;
          for (const [a, b] of overlay.skeleton) {
            const ja = f.joints[a];
            const jb = f.joints[b];
            if (!ja?.x || !jb?.x || ja.y == null || jb.y == null) continue;
            ctx.globalAlpha = ja.visible && jb.visible ? 0.95 : 0.35;
            ctx.beginPath();
            ctx.moveTo(ja.x, ja.y);
            ctx.lineTo(jb.x, jb.y);
            ctx.stroke();
          }
          ctx.globalAlpha = 1;

          const r = Math.max(5, overlay.width * 0.008);
          for (const [name, j] of Object.entries(f.joints)) {
            if (j.x == null || j.y == null) continue;
            if (name === "nose" || name === "ear") continue;
            ctx.beginPath();
            ctx.arc(j.x, j.y, r, 0, Math.PI * 2);
            // Green means the landmark was actually seen; orange means the model inferred it.
            ctx.fillStyle = j.visible ? COL.observed : COL.low;
            ctx.fill();
          }
        }

        if (showBarPath) {
          // The path travelled so far, so the line follows the movement rather than
          // pre-announcing it.
          ctx.lineWidth = Math.max(3, overlay.width * 0.004);
          ctx.beginPath();
          let started = false;
          for (const p of overlay.bar_path) {
            if (p.t > time || p.x == null || p.y == null) continue;
            if (!started) {
              ctx.moveTo(p.x, p.y);
              started = true;
            } else {
              ctx.lineTo(p.x, p.y);
            }
          }
          ctx.strokeStyle = COL.path;
          ctx.stroke();

          if (f.bar.x != null && f.bar.y != null) {
            const br = Math.max(7, overlay.width * 0.011);
            ctx.beginPath();
            ctx.arc(f.bar.x, f.bar.y, br, 0, Math.PI * 2);
            ctx.fillStyle = f.bar.observed ? COL.bar : COL.barEst;
            ctx.fill();
            if (!f.bar.observed) {
              // Dashed ring: this position is inferred from the shoulder, not detected.
              ctx.setLineDash([5, 5]);
              ctx.strokeStyle = COL.barEst;
              ctx.lineWidth = 2;
              ctx.beginPath();
              ctx.arc(f.bar.x, f.bar.y, br + 5, 0, Math.PI * 2);
              ctx.stroke();
              ctx.setLineDash([]);
            }
          }
        }

        if (highlightFrame != null && Math.abs(i - highlightFrame) <= 1) {
          ctx.strokeStyle = COL.bar;
          ctx.lineWidth = Math.max(4, overlay.width * 0.006);
          ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [overlay, showSkeleton, showBarPath, highlightFrame]);

  const rep = overlay.reps.find((r) => t >= r.start_t && t <= r.end_t);

  return (
    <div>
      <div className="stage-wrap">
        <video ref={videoRef} src={src} controls playsInline preload="auto" />
        <canvas ref={canvasRef} />
      </div>

      <div className="controls">
        <button
          className={`chip${showSkeleton ? " on" : ""}`}
          onClick={() => setShowSkeleton((v) => !v)}
        >
          Skeleton
        </button>
        <button
          className={`chip${showBarPath ? " on" : ""}`}
          onClick={() => setShowBarPath((v) => !v)}
        >
          Bar path
        </button>
        {overlay.reps.map((r) => (
          <button
            key={r.index}
            className={`chip${rep?.index === r.index ? " on" : ""}`}
            onClick={() => {
              const v = videoRef.current;
              if (v) {
                v.currentTime = r.bottom_t;
                v.pause();
              }
            }}
          >
            Rep {r.index} bottom
          </button>
        ))}
        <span className="faint" style={{ marginLeft: "auto", fontFamily: "var(--mono)" }}>
          {t.toFixed(2)}s
        </span>
      </div>

      <div className="legend">
        <span>
          <i className="swatch" style={{ background: COL.observed }} /> landmark seen
        </span>
        <span>
          <i className="swatch" style={{ background: COL.low }} /> landmark inferred
        </span>
        <span>
          <i className="swatch" style={{ background: COL.bar }} /> barbell detected
        </span>
        <span>
          <i className="swatch" style={{ background: COL.barEst }} /> barbell estimated
        </span>
      </div>
      <p className="faint" style={{ marginTop: 8 }}>
        Tracking the <strong>{overlay.side}</strong> side, which is the side facing the camera.
      </p>
    </div>
  );
});

export default VideoWithOverlay;
