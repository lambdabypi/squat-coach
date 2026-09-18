"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Overlay, OverlayFrame } from "@/lib/types";

export interface PlayerHandle {
  seek: (t: number) => void;
}

interface Props {
  src: string;
  overlay: Overlay;
  highlightFrame?: number | null;
  /** Which repetition the report is showing, so the target-pose toggle matches it. */
  activeRep?: number;
}

const COL = {
  observed: "#3fb950",
  low: "#f0883e",
  bone: "#58a6ff",
  bar: "#ffd166",
  barEst: "#8b949e",
  path: "rgba(255,209,102,.85)",
  pathEst: "rgba(139,148,158,.6)",
  angle: "#c792ea",
  angle2: "#7fd1e8",
  hipLine: "rgba(199,146,234,.5)",
  kneeLine: "rgba(127,209,232,.5)",
  ghost: "#5ef2c4",
};

/** Text with a dark outline so it stays readable over any footage. */
function label(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  scale: number,
  colour: string,
) {
  ctx.save();
  ctx.font = `600 ${Math.round(26 * scale)}px ui-monospace, Menlo, monospace`;
  ctx.lineWidth = 5 * scale;
  ctx.strokeStyle = "rgba(0,0,0,.85)";
  ctx.strokeText(text, x, y);
  ctx.fillStyle = colour;
  ctx.fillText(text, x, y);
  ctx.restore();
}

/**
 * Canvas overlay synchronised to <video>.currentTime.
 *
 * We draw on top of the original file rather than re-encoding an annotated MP4: the result is
 * available the instant analysis finishes, it stays sharp at any size, and it is scrubbable.
 * The brief accepts "playable annotated video or synchronized video overlays".
 */
const VideoWithOverlay = forwardRef<PlayerHandle, Props>(function VideoWithOverlay(
  { src, overlay, highlightFrame, activeRep },
  ref,
) {
  const activeTarget =
    activeRep != null ? overlay.target_poses?.[String(activeRep)] : undefined;
  const hasTargetForActiveRep = !!activeTarget && activeTarget.corrections.length > 0;

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [showBarPath, setShowBarPath] = useState(true);
  const [showAngles, setShowAngles] = useState(true);
  const [showGhost, setShowGhost] = useState(true);
  const [t, setT] = useState(0);
  const [live, setLive] = useState<OverlayFrame["angles"] | null>(null);

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
      setLive(f?.angles ?? null);

      // When the target is shown, the athlete's own pose recedes so the comparison reads as
      // "you (faint) versus target (bright)" instead of two equally loud skeletons.
      const ghostFor = showGhost
        ? Object.values(overlay.target_poses ?? {}).find((p) => Math.abs(p.frame - i) <= 1)
        : undefined;
      const dim = ghostFor ? 0.3 : 1;

      if (f) {
        if (showAngles && !ghostFor) {
          const S = overlay.width / 1080; // scale annotation weight with resolution
          const j = f.joints;

          // Plumb line through the midfoot: the document's balance reference. The bar should
          // travel along this line (ref p.8-9).
          if (f.angles.midfoot_x != null) {
            ctx.save();
            ctx.strokeStyle = "rgba(88,166,255,.55)";
            ctx.lineWidth = 2 * S;
            ctx.setLineDash([10 * S, 8 * S]);
            ctx.beginPath();
            ctx.moveTo(f.angles.midfoot_x, 0);
            ctx.lineTo(f.angles.midfoot_x, canvas.height);
            ctx.stroke();
            ctx.restore();
          }

          // Back angle: arc from horizontal up to the torso, drawn at the hip.
          if (f.angles.back != null && j.hip?.x != null && j.shoulder?.x != null) {
            const hx = j.hip.x!;
            const hy = j.hip.y!;
            const r = 70 * S;
            const toShoulder = Math.atan2(j.shoulder.y! - hy, j.shoulder.x! - hx);
            const facing = j.shoulder.x! < hx ? Math.PI : 0;
            ctx.save();
            ctx.strokeStyle = COL.angle;
            ctx.lineWidth = 3 * S;
            ctx.beginPath();
            ctx.moveTo(hx, hy);
            ctx.lineTo(hx + Math.cos(facing) * r, hy);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(hx, hy, r, Math.min(facing, toShoulder), Math.max(facing, toShoulder));
            ctx.stroke();
            ctx.restore();
            label(ctx, `${f.angles.back.toFixed(0)}°`, hx + Math.cos(facing) * r * 1.25, hy - 12 * S, S, COL.angle);
          }

          // Knee angle.
          if (f.angles.knee != null && j.knee?.x != null) {
            label(ctx, `${f.angles.knee.toFixed(0)}°`, j.knee.x! + 22 * S, j.knee.y! + 6 * S, S, COL.angle2);
          }

          // Depth cue: horizontal guides at hip and knee height make the document's depth
          // standard (hip below top of patella) legible frame by frame.
          if (j.hip?.y != null && j.knee?.y != null) {
            ctx.save();
            ctx.lineWidth = 2 * S;
            ctx.setLineDash([6 * S, 6 * S]);
            for (const [y, c] of [[j.hip.y!, COL.hipLine], [j.knee.y!, COL.kneeLine]] as const) {
              ctx.strokeStyle = c;
              ctx.beginPath();
              ctx.moveTo(0, y);
              ctx.lineTo(canvas.width, y);
              ctx.stroke();
            }
            ctx.restore();
          }
        }

        if (showSkeleton) {
          // Bones first, joints on top.
          ctx.lineWidth = Math.max(3, overlay.width * 0.005);
          ctx.strokeStyle = COL.bone;
          for (const [a, b] of overlay.skeleton) {
            const ja = f.joints[a];
            const jb = f.joints[b];
            if (!ja?.x || !jb?.x || ja.y == null || jb.y == null) continue;
            ctx.globalAlpha = (ja.visible && jb.visible ? 0.95 : 0.35) * dim;
            ctx.beginPath();
            ctx.moveTo(ja.x, ja.y);
            ctx.lineTo(jb.x, jb.y);
            ctx.stroke();
          }
          ctx.globalAlpha = dim;

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
          ctx.globalAlpha = 1;
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

        // Corrected-pose ghost: their own limb lengths, solved for the document's geometry.
        // Only drawn at the bottom frame it was solved for, so it is never confused with a
        // claim about the rest of the movement.
        if (ghostFor) {
          const tp = ghostFor;
          const S = overlay.width / 1080;
          const actualHip = f.joints.hip;

          // One idea per annotation. The headline is depth, so the headline mark is a single
          // horizontal band from where the hip finished to where it needed to be - the
          // earlier full-skeleton ghost drew four bright segments over four existing ones and
          // read as noise rather than as an instruction.
          if (actualHip?.x != null) {
            const yFrom = actualHip.y!;
            const yTo = tp.hip[1];
            ctx.save();
            ctx.fillStyle = "rgba(94,242,196,.16)";
            ctx.fillRect(0, Math.min(yFrom, yTo), canvas.width, Math.abs(yTo - yFrom));

            ctx.strokeStyle = COL.ghost;
            ctx.lineWidth = 4 * S;
            ctx.beginPath();
            ctx.moveTo(0, yTo);
            ctx.lineTo(canvas.width, yTo);
            ctx.stroke();

            // Arrow showing which way to travel.
            const cx = tp.hip[0];
            ctx.lineWidth = 5 * S;
            ctx.beginPath();
            ctx.moveTo(cx, yFrom);
            ctx.lineTo(cx, yTo);
            ctx.stroke();
            const dir = Math.sign(yTo - yFrom) || 1;
            ctx.beginPath();
            ctx.moveTo(cx, yTo);
            ctx.lineTo(cx - 12 * S, yTo - dir * 18 * S);
            ctx.moveTo(cx, yTo);
            ctx.lineTo(cx + 12 * S, yTo - dir * 18 * S);
            ctx.stroke();
            ctx.restore();

            label(ctx, "sit to here", 16 * S, yTo - 14 * S, S, COL.ghost);
          }

          // The target leg, thin and dashed: enough to show the shape, quiet enough not to
          // compete with the athlete's own body.
          ctx.save();
          ctx.globalAlpha = 0.9;
          ctx.setLineDash([10 * S, 9 * S]);
          ctx.lineWidth = 3 * S;
          ctx.strokeStyle = COL.ghost;
          const chain: [number, number][] = [tp.ankle, tp.knee, tp.hip];
          ctx.beginPath();
          ctx.moveTo(chain[0][0], chain[0][1]);
          for (const p of chain.slice(1)) ctx.lineTo(p[0], p[1]);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.arc(tp.hip[0], tp.hip[1], 11 * S, 0, Math.PI * 2);
          ctx.fillStyle = COL.ghost;
          ctx.fill();
          ctx.restore();
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
  }, [overlay, showSkeleton, showBarPath, showAngles, showGhost, highlightFrame]);

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
        <button
          className={`chip${showAngles ? " on" : ""}`}
          onClick={() => setShowAngles((v) => !v)}
        >
          Angles
        </button>
        {/* Scoped to the repetition on screen. Showing it whenever ANY rep had a target pose
            meant selecting a clean repetition left a toggle that drew nothing. */}
        {hasTargetForActiveRep && (
          <button
            className={`chip${showGhost ? " on" : ""}`}
            onClick={() => setShowGhost((v) => !v)}
          >
            Target pose
          </button>
        )}
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

      {showAngles && live && (
        <div className="readout">
          <Readout
            name="Back angle"
            value={live.back == null ? null : `${live.back.toFixed(0)}°`}
            target={
              overlay.targets.back?.reference != null
                ? `target ~${overlay.targets.back.reference}°`
                : null
            }
            note={
              overlay.targets.back?.tolerance != null
                ? `±${overlay.targets.back.tolerance}° ${
                    overlay.targets.back.tolerance_provenance === "document_stated"
                      ? "per document"
                      : "our tolerance"
                  }`
                : null
            }
            ok={
              live.back != null &&
              overlay.targets.back?.reference != null &&
              overlay.targets.back?.tolerance != null &&
              Math.abs(live.back - overlay.targets.back.reference) <=
                overlay.targets.back.tolerance
            }
            colour={COL.angle}
          />
          <Readout
            name="Knee angle"
            value={live.knee == null ? null : `${live.knee.toFixed(0)}°`}
            target={null}
            note="observed, no document standard"
            colour={COL.angle2}
          />
          <Readout
            name="Bar vs midfoot"
            value={live.bar_dev == null ? null : `${live.bar_dev >= 0 ? "+" : ""}${live.bar_dev.toFixed(2)} shin`}
            target="target 0.00"
            note={
              overlay.targets.bar_dev?.tolerance != null
                ? `±${overlay.targets.bar_dev.tolerance} our tolerance`
                : null
            }
            ok={
              live.bar_dev != null &&
              overlay.targets.bar_dev?.tolerance != null &&
              Math.abs(live.bar_dev) <= overlay.targets.bar_dev.tolerance
            }
            colour={COL.bar}
          />
        </div>
      )}

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

function Readout({
  name,
  value,
  target,
  note,
  ok,
  colour,
}: {
  name: string;
  value: string | null;
  target: string | null;
  note: string | null;
  ok?: boolean;
  colour: string;
}) {
  return (
    <div className="readout-cell">
      <div className="readout-name">{name}</div>
      <div
        className="readout-value"
        style={{ color: value == null ? "var(--faint)" : ok === false ? "var(--fail)" : colour }}
      >
        {value ?? "-"}
      </div>
      {target && <div className="readout-target">{target}</div>}
      {note && <div className="readout-note">{note}</div>}
    </div>
  );
}

export default VideoWithOverlay;
