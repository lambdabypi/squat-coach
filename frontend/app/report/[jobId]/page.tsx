"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import FindingCard from "@/components/FindingCard";
import VideoWithOverlay, { type PlayerHandle } from "@/components/VideoWithOverlay";
import { getOverlay, getReport, videoUrl } from "@/lib/api";
import type { Overlay, Report } from "@/lib/types";

export default function ReportPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const [report, setReport] = useState<Report | null>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeRep, setActiveRep] = useState(1);
  const [highlight, setHighlight] = useState<number | null>(null);
  const player = useRef<PlayerHandle>(null);

  useEffect(() => {
    Promise.all([getReport(jobId), getOverlay(jobId)])
      .then(([r, o]) => {
        setReport(r);
        setOverlay(o);
        if (r.reps.length) setActiveRep(r.reps[0].index);
      })
      .catch((e) => setError((e as Error).message));
  }, [jobId]);

  const findings = useMemo(
    () => report?.findings.filter((f) => f.rep_index === activeRep) ?? [],
    [report, activeRep],
  );

  const counts = useMemo(() => {
    const c = { meets_standard: 0, does_not_meet_standard: 0, cannot_assess: 0 };
    for (const f of findings) c[f.verdict]++;
    return c;
  }, [findings]);

  if (error) {
    return (
      <main className="wrap narrow">
        <div className="notice bad">{error}</div>
        <a className="btn secondary" href="/">
          Start over
        </a>
      </main>
    );
  }

  if (!report || !overlay) {
    return (
      <main className="wrap narrow">
        <p className="muted">Loading the assessment…</p>
      </main>
    );
  }

  const degraded = report.quality.gates.filter((g) => g.severity === "degraded" || !g.passed);

  return (
    <main className="wrap">
      <h2 style={{ marginTop: 8 }}>{report.video.filename}</h2>
      <p className="faint" style={{ marginTop: -6 }}>
        {report.reps.length} repetition{report.reps.length === 1 ? "" : "s"} ·{" "}
        {report.video.width}×{report.video.height} at {report.video.fps.toFixed(0)}fps ·{" "}
        assessed against {report.skill.document} (skill v{report.skill.version})
        {report.findings.some((f) => f.narrated_by === "agent") ? " · narrated by the agent" : ""}
      </p>

      {report.blocked ? (
        <div className="notice bad" style={{ padding: "16px 18px" }}>
          <h3 style={{ marginTop: 0 }}>This video could not be assessed</h3>
          {report.quality.blocking_reasons.map((r) => (
            <p key={r} style={{ marginBottom: 8 }}>
              {r}
            </p>
          ))}
          <p style={{ marginBottom: 0 }}>
            No repetition was judged against the reference standards. Reporting verdicts from
            footage this unreliable would mean inventing conclusions the video does not support.
            The tracking below is still shown so you can see what was and was not picked up.
          </p>
        </div>
      ) : (
        report.summary && (
          <div className="card">
            <h3>Overall</h3>
            <p style={{ marginBottom: 0 }}>{report.summary}</p>
          </div>
        )
      )}

      {report.agent_note && <div className="notice warn">{report.agent_note}</div>}
      {report.rep_note && <div className="notice">{report.rep_note}</div>}

      <div className="grid">
        <div>
          <VideoWithOverlay
            ref={player}
            src={videoUrl(jobId)}
            overlay={overlay}
            highlightFrame={highlight}
          />

          {(() => {
            const tp = overlay.target_poses?.[String(activeRep)];
            if (!tp || tp.corrections.length === 0) return null;
            return (
              <>
                <h2>How to fix it — repetition {activeRep}</h2>
                <div className="card">
                  <p className="muted" style={{ marginTop: 0 }}>
                    The dashed target on the video is <strong>your</strong> body: the same shin,
                    thigh and torso lengths measured from this video, with your foot planted where
                    it actually was, solved for the position the reference document describes. It
                    is not a stock animation of someone else.
                  </p>
                  {tp.corrections.map((c) => (
                    <div key={c.criterion_id} className="feedback" style={{ marginTop: 10 }}>
                      <strong>{c.label}.</strong> {c.detail}
                      <div className="faint" style={{ marginTop: 6 }}>
                        {c.provenance.includes("engineering")
                          ? "The rule comes from the document; the size of the target margin is our choice, not the document's."
                          : "Stated in the reference document."}
                      </div>
                    </div>
                  ))}
                  <button
                    className="chip"
                    style={{ marginTop: 12 }}
                    onClick={() => {
                      player.current?.seek(tp.t);
                      setHighlight(tp.frame);
                    }}
                  >
                    ▸ Jump to {tp.t.toFixed(2)}s and compare
                  </button>
                  <p className="faint" style={{ marginTop: 12, marginBottom: 0 }}>
                    Shown in two dimensions only. This is a single side-on camera, so we never
                    measured depth and do not render it. The target says nothing about knees-out
                    or stance — a side view cannot see either.
                  </p>
                  {!tp.solved && tp.note && <p className="uncertain">{tp.note}</p>}
                </div>
              </>
            );
          })()}

          <h2>Recording quality</h2>
          <div className="card">
            {report.quality.gates.map((g) => (
              <div key={g.id} style={{ display: "flex", gap: 10, marginBottom: 8 }}>
                <span
                  className={`verdict-badge ${
                    !g.passed
                      ? "v-does_not_meet_standard"
                      : g.severity === "degraded"
                        ? "v-cannot_assess"
                        : "v-meets_standard"
                  }`}
                >
                  {!g.passed ? "issue" : g.severity === "degraded" ? "partial" : "ok"}
                </span>
                <span className="muted" style={{ fontSize: 13 }}>
                  {g.detail}
                </span>
              </div>
            ))}
            <p className="faint" style={{ marginTop: 10, marginBottom: 0 }}>
              Barbell detected in {(report.bar.observed_fraction * 100).toFixed(0)}% of frames ·
              pose found in {(report.pose.detection_fraction * 100).toFixed(0)}% ·
              measurements normalised by a {report.pose.shin_length_px}px shin length.
            </p>
          </div>

          <h2>What this camera angle cannot judge</h2>
          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>Criterion</th>
                  <th>Why not</th>
                  <th>Needs</th>
                </tr>
              </thead>
              <tbody>
                {report.coverage
                  .filter((c) => c.assessable === "none")
                  .map((c) => (
                    <tr key={c.id}>
                      <td>
                        {c.name}
                        <div className="faint">{c.citation}</div>
                      </td>
                      <td className="muted">{c.reason}</td>
                      <td className="faint">{c.needed}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          {report.cost && (
            <p className="faint">
              Assessment cost: ${(report.cost.estimated_usd as number)?.toFixed(4)} ·{" "}
              {String(report.cost.model)} ·{" "}
              {String(report.cost.output_tokens)} output tokens
            </p>
          )}
        </div>

        <aside>
          <div className="controls" style={{ marginTop: 0, marginBottom: 12 }}>
            {report.reps.map((r) => (
              <button
                key={r.index}
                className={`chip${activeRep === r.index ? " on" : ""}`}
                onClick={() => {
                  setActiveRep(r.index);
                  player.current?.seek(r.bottom_t);
                  setHighlight(r.bottom_frame);
                }}
              >
                Rep {r.index}
              </button>
            ))}
          </div>

          <p className="faint" style={{ marginTop: 0 }}>
            {counts.meets_standard} met · {counts.does_not_meet_standard} not met ·{" "}
            {counts.cannot_assess} could not be assessed
          </p>

          {degraded.length > 0 && (
            <div className="notice warn">
              {degraded.length} quality issue{degraded.length === 1 ? "" : "s"} affect what can be
              concluded from this footage. See recording quality below the video.
            </div>
          )}

          {report.blocked && (
            <div className="notice">
              Findings are withheld for this video. Fix the recording issues listed above and
              upload again.
            </div>
          )}

          {findings.map((f) => (
            <FindingCard
              key={`${f.rep_index}-${f.criterion_id}`}
              finding={f}
              onSeek={(t, frame) => {
                player.current?.seek(t);
                setHighlight(frame);
              }}
            />
          ))}
        </aside>
      </div>

      <p style={{ marginTop: 30 }}>
        <a className="btn secondary" href="/">
          Analyse another video
        </a>
      </p>
    </main>
  );
}
