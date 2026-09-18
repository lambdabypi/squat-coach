"use client";

import { useEffect, useRef, useState } from "react";
import type { PreviewFrame } from "@/lib/api";

const BONES: [string, string][] = [
  ["shoulder", "hip"],
  ["hip", "knee"],
  ["knee", "ankle"],
  ["ankle", "toe"],
  ["ankle", "heel"],
];

/**
 * Watch the analysis happen.
 *
 * The file is already in the browser, so the video plays from a local object URL with zero
 * transfer, while the backend streams back the landmarks it has computed so far. Seeking the
 * playhead to the most recently analysed frame means the user sees tracking progress through
 * their own clip rather than a progress bar with nothing behind it.
 *
 * These landmarks are a progress view, not evidence: the camera-facing side is not known until
 * the whole clip has been read, so this always draws the left chain. The report redraws
 * everything from the finished analysis.
 */
export default function LiveTracking({
  frames,
  file,
}: {
  frames: PreviewFrame[];
  file: File | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // The draw loop reads from a ref so it does not re-subscribe on every new batch.
  const framesRef = useRef<PreviewFrame[]>([]);
  const rafRef = useRef(0);
  const [url, setUrl] = useState<string | null>(null);
  const [fps, setFps] = useState(30);
  const analysed = frames.length;

  framesRef.current = frames;

  useEffect(() => {
    if (!file) return;
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  // Draw the most recent landmarks and keep the playhead on that frame.
  //
  // `url` MUST stay in the dependency list. This component returns null until the object URL
  // exists, so on first mount there is no <video> and no <canvas> and the refs are null. With
  // only [fps] here the effect bailed on that first run and never fired again once the elements
  // appeared - landmarks streamed in correctly and nothing was ever painted.
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const draw = () => {
      const list = framesRef.current;
      const latest = list[list.length - 1];
      const ctx = canvas.getContext("2d");
      if (ctx && latest) {
        if (canvas.width !== video.videoWidth && video.videoWidth) {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
        }
        const W = canvas.width;
        const H = canvas.height;
        ctx.clearRect(0, 0, W, H);

        const S = W / 1080;
        const P = (n: string) => {
          const j = latest.joints[n];
          return j ? ([j[0] * W, j[1] * H, j[2]] as const) : null;
        };

        ctx.lineWidth = Math.max(3, 5 * S);
        ctx.strokeStyle = "#58a6ff";
        for (const [a, b] of BONES) {
          const pa = P(a);
          const pb = P(b);
          if (!pa || !pb) continue;
          ctx.globalAlpha = Math.min(pa[2], pb[2]) > 0.6 ? 0.95 : 0.3;
          ctx.beginPath();
          ctx.moveTo(pa[0], pa[1]);
          ctx.lineTo(pb[0], pb[1]);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        for (const n of Object.keys(latest.joints)) {
          const p = P(n);
          if (!p) continue;
          ctx.beginPath();
          ctx.arc(p[0], p[1], Math.max(5, 9 * S), 0, Math.PI * 2);
          ctx.fillStyle = p[2] > 0.6 ? "#3fb950" : "#f0883e";
          ctx.fill();
        }

        // Keep the frame under inspection on screen. Tracking runs slower than playback, so
        // the video is driven by the analysis rather than by the clock.
        const target = latest.frame / fps;
        if (Number.isFinite(target) && Math.abs(video.currentTime - target) > 0.08) {
          try {
            video.currentTime = target;
          } catch {
            /* seeking before metadata is ready */
          }
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [fps, url]);

  if (!url) return null;

  return (
    <div style={{ marginTop: 14 }}>
      <div className="stage-wrap">
        <video
          ref={videoRef}
          src={url}
          muted
          playsInline
          preload="auto"
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            // Size the canvas as soon as the real dimensions are known, rather than waiting for
            // the draw loop to notice - otherwise the first frames paint into a 300x150 default
            // and appear stretched.
            const c = canvasRef.current;
            if (c && v.videoWidth) {
              c.width = v.videoWidth;
              c.height = v.videoHeight;
            }
            // No frame-rate API in the browser; 30fps covers the overwhelming majority of
            // phone footage and this view only needs to land near the right frame.
            setFps(30);
            v.pause();
          }}
        />
        <canvas ref={canvasRef} />
      </div>
      <p className="faint" style={{ marginTop: 8, marginBottom: 0 }}>
        Landmarks streamed back for {analysed} frames so far, drawn as they arrive. Green means the
        joint was seen, orange means the model is inferring it. The video itself plays from your
        own device - only the landmark coordinates travel back over the network.
      </p>
    </div>
  );
}
