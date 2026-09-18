"use client";

import { useEffect, useRef } from "react";
import type { OverlayFrame, TargetPose } from "@/lib/types";

type Pt = [number, number];

/**
 * Two stick figures side by side: the position the athlete reached, and the position the
 * document describes, drawn from the same data at the same scale.
 *
 * Overlaying both on the video is good for "is the tracking right?", but poor for "what do I
 * change?" - the two chains sit on top of each other and neither reads cleanly. Separating
 * them answers the second question, which is the one the user has after they trust the first.
 */
export default function PoseCompare({
  frame,
  target,
  shinPx,
}: {
  frame: OverlayFrame;
  target: TargetPose;
  shinPx: number | null;
}) {
  const yourRef = useRef<HTMLCanvasElement>(null);
  const targetRef = useRef<HTMLCanvasElement>(null);

  const j = frame.joints;
  const actual: Record<string, Pt> | null =
    j.ankle?.x != null && j.knee?.x != null && j.hip?.x != null && j.shoulder?.x != null
      ? {
          ankle: [j.ankle.x!, j.ankle.y!],
          knee: [j.knee.x!, j.knee.y!],
          hip: [j.hip.x!, j.hip.y!],
          shoulder: [j.shoulder.x!, j.shoulder.y!],
          toe: j.toe?.x != null ? [j.toe.x!, j.toe.y!] : [j.ankle.x!, j.ankle.y!],
        }
      : null;

  const wanted: Record<string, Pt> = {
    ankle: target.ankle,
    knee: target.knee,
    hip: target.hip,
    shoulder: target.shoulder,
    toe: actual?.toe ?? target.ankle,
  };

  useEffect(() => {
    if (!actual) return;
    // One shared transform so the two figures are directly comparable - different scales would
    // make a deeper squat look like a smaller person.
    const all = [...Object.values(actual), ...Object.values(wanted)];
    const xs = all.map((p) => p[0]);
    const ys = all.map((p) => p[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const pad = 26;

    const render = (
      canvas: HTMLCanvasElement | null,
      pts: Record<string, Pt>,
      colour: string,
      dashed: boolean,
    ) => {
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      const scale = Math.min(
        (W - pad * 2) / Math.max(maxX - minX, 1),
        (H - pad * 2) / Math.max(maxY - minY, 1),
      );
      const ox = (W - (maxX - minX) * scale) / 2;
      const oy = (H - (maxY - minY) * scale) / 2;
      const T = (p: Pt): Pt => [(p[0] - minX) * scale + ox, (p[1] - minY) * scale + oy];

      // Ground line at the foot.
      const ground = T(pts.ankle)[1] + 10;
      ctx.strokeStyle = "rgba(255,255,255,.14)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(8, ground);
      ctx.lineTo(W - 8, ground);
      ctx.stroke();

      // Hip and knee height guides - the depth standard, made visible.
      const hip = T(pts.hip);
      const knee = T(pts.knee);
      ctx.setLineDash([4, 5]);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "rgba(199,146,234,.55)";
      ctx.beginPath();
      ctx.moveTo(8, hip[1]);
      ctx.lineTo(W - 8, hip[1]);
      ctx.stroke();
      ctx.strokeStyle = "rgba(127,209,232,.55)";
      ctx.beginPath();
      ctx.moveTo(8, knee[1]);
      ctx.lineTo(W - 8, knee[1]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Body.
      const chain: Pt[] = [pts.shoulder, pts.hip, pts.knee, pts.ankle].map(T);
      ctx.strokeStyle = colour;
      ctx.lineWidth = 5;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      if (dashed) ctx.setLineDash([9, 7]);
      ctx.beginPath();
      ctx.moveTo(chain[0][0], chain[0][1]);
      for (const p of chain.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Foot.
      const toe = T(pts.toe);
      ctx.beginPath();
      ctx.moveTo(chain[3][0], chain[3][1]);
      ctx.lineTo(toe[0], toe[1]);
      ctx.stroke();

      for (const p of chain) {
        ctx.beginPath();
        ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
        ctx.fillStyle = colour;
        ctx.fill();
      }

      // Head, so it reads as a person rather than a diagram.
      const head: Pt = [
        chain[0][0] + (chain[0][0] - chain[1][0]) * 0.22,
        chain[0][1] + (chain[0][1] - chain[1][1]) * 0.22,
      ];
      ctx.beginPath();
      ctx.arc(head[0], head[1], 13, 0, Math.PI * 2);
      ctx.strokeStyle = colour;
      ctx.lineWidth = 4;
      ctx.stroke();
    };

    render(yourRef.current, actual, "#58a6ff", false);
    render(targetRef.current, wanted, "#5ef2c4", true);
  }, [actual, wanted]);

  if (!actual || !shinPx) return null;

  const gotDepth = (actual.hip[1] - actual.knee[1]) / shinPx;
  const wantDepth = (wanted.hip[1] - wanted.knee[1]) / shinPx;

  return (
    <div className="compare">
      <figure>
        <canvas ref={yourRef} width={320} height={300} />
        <figcaption>
          <strong style={{ color: "#58a6ff" }}>Where you were</strong>
          <span className="faint">
            hip {gotDepth >= 0 ? "" : "-"}
            {Math.abs(gotDepth).toFixed(2)} shin {gotDepth >= 0 ? "below" : "above"} knee
          </span>
        </figcaption>
      </figure>
      <div className="compare-arrow">→</div>
      <figure>
        <canvas ref={targetRef} width={320} height={300} />
        <figcaption>
          <strong style={{ color: "#5ef2c4" }}>Where to get to</strong>
          <span className="faint">hip {wantDepth.toFixed(2)} shin below knee</span>
        </figcaption>
      </figure>
    </div>
  );
}
