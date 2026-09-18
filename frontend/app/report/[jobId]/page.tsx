"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import FindingCard from "@/components/FindingCard";
import PoseCompare from "@/components/PoseCompare";
import VideoWithOverlay, { type PlayerHandle } from "@/components/VideoWithOverlay";
import { getOverlay, getReport, videoUrl } from "@/lib/api";
import { localVideoUrl } from "@/lib/localVideo";
import { groupFindings, headline, presentMeasurement } from "@/lib/present";
import type { Finding, Overlay, Report } from "@/lib/types";

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
  const groups = useMemo(() => groupFindings(findings), [findings]);

  const jump = (t: number | null, frame: number | null) => {
    if (t != null) player.current?.seek(t);
    setHighlight(frame);
  };

  if (error) {
    return (
      <main className="wrap narrow">
        <div className="notice bad">{error}</div>
        <a className="btn secondary" href="/">Start over</a>
      </main>
    );
  }

  if (!report || !overlay) {
    return (
      <main className="wrap narrow">
        <p className="muted">Loading your assessment...</p>
      </main>
    );
  }

  const rep = report;
  const ov = overlay;
  const topFix = groups.fix[0] ?? null;
  const targetPose = ov.target_poses?.[String(activeRep)];
  const issues = rep.quality.gates.filter((g) => g.severity !== "ok");

  const card = (f: Finding) => (
    <FindingCard key={f.criterion_id} finding={f} report={rep} onSeek={jump} />
  );

  return (
    <main className="wrap">
      {/* Rep selector first. Everything below is scoped to one repetition and that has to be
          obvious before anything else is read. */}
      <div className="repbar">
        <span className="repbar-label">Repetition</span>
        {rep.reps.map((r) => (
          <button
            key={r.index}
            className={`repchip${activeRep === r.index ? " on" : ""}`}
            onClick={() => {
              setActiveRep(r.index);
              jump(r.bottom_t, r.bottom_frame);
            }}
          >
            {r.index}
          </button>
        ))}
        <span className="faint" style={{ marginLeft: "auto" }}>{rep.video.filename}</span>
      </div>

      {rep.blocked ? (
        <div className="notice bad" style={{ padding: "18px 20px" }}>
          <h3 style={{ marginTop: 0 }}>This video could not be assessed</h3>
          {rep.quality.blocking_reasons.map((r) => (
            <p key={r} style={{ marginBottom: 8 }}>{r}</p>
          ))}
          <p style={{ marginBottom: 0 }}>
            No repetition was judged against the reference standards. Reporting verdicts from
            footage this unreliable would mean inventing conclusions the video does not support.
          </p>
        </div>
      ) : (
        <>
          <h2 className="hero-line">{headline(findings)}</h2>

          {topFix && (
            <section className="fixfirst">
              <div className="fixfirst-tag">Fix this first</div>
              <h3>{topFix.criterion_name}</h3>
              <p className="fixfirst-what">{topFix.explanation}</p>
              {topFix.feedback && <p className="fixfirst-do">{topFix.feedback}</p>}
              <div className="fixfirst-foot">
                {topFix.timestamp_s != null && (
                  <button
                    className="btn"
                    onClick={() => jump(topFix.timestamp_s, topFix.frame_index)}
                  >
                    Watch it at {topFix.timestamp_s.toFixed(2)}s
                  </button>
                )}
                {(() => {
                  const p = presentMeasurement(topFix, rep);
                  return p ? <span className="pill obs">{p.primary}</span> : null;
                })()}
                <span className="pill">{topFix.citation}</span>
              </div>
            </section>
          )}
        </>
      )}

      <div className="grid">
        <div className="sticky-col">
          <VideoWithOverlay
            ref={player}
            src={localVideoUrl(jobId) ?? videoUrl(jobId)}
            overlay={ov}
            highlightFrame={highlight}
          />
        </div>

        <aside>
          {rep.blocked ? (
            <div className="notice">
              Findings are withheld for this video. Fix the recording issues above and upload
              again.
            </div>
          ) : (
            <>
              <Group
                title={groups.fix.length === 1 ? "1 thing to work on" : `${groups.fix.length} things to work on`}
                tone="fail"
                count={groups.fix.length}
                open
              >
                {groups.fix.map(card)}
              </Group>

              <Group
                title={groups.good.length === 1 ? "1 thing you are doing right" : `${groups.good.length} things you are doing right`}
                tone="pass"
                count={groups.good.length}
              >
                {groups.good.map(card)}
              </Group>

              <Group
                title={`${groups.borderline.length} too close to call`}
                tone="unknown"
                count={groups.borderline.length}
                blurb="We measured these, but the result sits inside our measurement tolerance. That is a limit of the measurement, not of your camera angle."
              >
                {groups.borderline.map(card)}
              </Group>

              <Group
                title={`${groups.unseen.length} we could not judge`}
                tone="unknown"
                count={groups.unseen.length}
                blurb="A side-on camera cannot see some of these at all, and others were hidden in the frames we needed. We would rather say so than guess."
              >
                {groups.unseen.map(card)}
              </Group>
            </>
          )}
        </aside>
      </div>

      {targetPose && targetPose.corrections.length > 0 && (
        <section>
          <h2>What to change</h2>
          <div className="card">
            <PoseCompare
              frame={ov.frames[targetPose.frame]}
              target={targetPose}
              shinPx={ov.shin_length_px}
            />
            <p className="muted">
              That target is <strong>your</strong> body: the same shin, thigh and torso lengths
              measured from this video, with your foot planted where it actually was, solved for
              the position the reference document describes. It is not a stock animation of
              someone else.
            </p>
            {targetPose.corrections.map((c) => (
              <div key={c.criterion_id} className="feedback" style={{ marginTop: 10 }}>
                <strong>{c.label}.</strong> {c.detail}
              </div>
            ))}
            <button
              className="chip"
              style={{ marginTop: 12 }}
              onClick={() => jump(targetPose.t, targetPose.frame)}
            >
              Compare on the video at {targetPose.t.toFixed(2)}s
            </button>
            <p className="faint" style={{ marginTop: 12, marginBottom: 0 }}>
              Shown in two dimensions only. This is a single side-on camera, so we never measured
              depth and do not draw it.
            </p>
          </div>
        </section>
      )}

      {/* Everything that earns trust rather than delivering value sits below, collapsed. */}
      <section style={{ marginTop: 34 }}>
        <details className="drawer" open={issues.length > 0}>
          <summary>
            How good was this recording?
            {issues.length > 0 && <span className="drawer-badge">{issues.length}</span>}
          </summary>
          <div className="drawer-body">
            {rep.quality.gates.map((g) => (
              <div key={g.id} className="qualityrow">
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
                <span className="muted">{g.detail}</span>
              </div>
            ))}
            <p className="faint" style={{ marginBottom: 0 }}>
              Barbell tracked through {((rep.bar.usable_fraction ?? rep.bar.observed_fraction) * 100).toFixed(0)}%
              of frames ({(rep.bar.observed_fraction * 100).toFixed(0)}% detected directly), pose
              found in {(rep.pose.detection_fraction * 100).toFixed(0)}%, tracking the{" "}
              {rep.pose.side} side.
            </p>
          </div>
        </details>

        <details className="drawer">
          <summary>What a side view cannot judge</summary>
          <div className="drawer-body">
            <table>
              <thead>
                <tr><th>Criterion</th><th>Why not</th><th>Needs</th></tr>
              </thead>
              <tbody>
                {rep.coverage
                  .filter((c) => c.assessable === "none")
                  .map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}<div className="faint">{c.citation}</div></td>
                      <td className="muted">{c.reason}</td>
                      <td className="faint">{c.needed}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>

        <details className="drawer">
          <summary>How this was measured</summary>
          <div className="drawer-body">
            <p className="muted">{rep.summary}</p>
            <p className="faint">
              Assessed against {rep.skill.document}, skill v{rep.skill.version}. Distances are
              normalised by a {rep.pose.shin_length_px}px shin length so they compare across body
              sizes and framings.
            </p>
            {rep.scale && (
              <p className="faint">
                Centimetre figures use the barbell plate as a ruler. {rep.scale.assumption}
              </p>
            )}
            {rep.agent_note && <p className="uncertain">{rep.agent_note}</p>}
            {rep.cost && (
              <p className="faint">
                Assessment cost ${(rep.cost.estimated_usd as number)?.toFixed(4)} using{" "}
                {String(rep.cost.model)}.
              </p>
            )}
          </div>
        </details>
      </section>

      <p style={{ marginTop: 30 }}>
        <a className="btn secondary" href="/">Analyse another video</a>
      </p>
    </main>
  );
}

function Group({
  title,
  tone,
  count,
  open,
  blurb,
  children,
}: {
  title: string;
  tone: "pass" | "fail" | "unknown";
  count: number;
  open?: boolean;
  blurb?: string;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <details className={`group group-${tone}`} open={open}>
      <summary>
        <span className="group-dot" />
        {title}
      </summary>
      <div className="group-body">
        {blurb && <p className="faint group-blurb">{blurb}</p>}
        {children}
      </div>
    </details>
  );
}
