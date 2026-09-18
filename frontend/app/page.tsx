"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import LiveTracking from "@/components/LiveTracking";
import { getRequirements, subscribeToJob, uploadVideo, type PreviewFrame } from "@/lib/api";
import { submitClientAnalysis, trackInBrowser } from "@/lib/clientPose";
import { rememberLocalVideo } from "@/lib/localVideo";
import type { JobStatus, Requirements } from "@/lib/types";

const STAGE_ORDER = [
  "Checking the video",
  "Tracking the movement",
  "Finding repetitions",
  "Checking evidence quality",
  "Measuring against the standards",
  "Writing the assessment",
];

export default function Home() {
  const router = useRouter();
  const [reqs, setReqs] = useState<Requirements | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewFrame[]>([]);
  const [tracking, setTracking] = useState<{ frame: number; total: number } | null>(null);
  const [fellBack, setFellBack] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getRequirements()
      .then(setReqs)
      .catch((e) => setReqError(e.message));
  }, []);

  // One held-open stream for the whole analysis, rather than an interval poll. See
  // subscribeToJob for why this matters on Cloud Run as well as in the browser.
  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return;
    setPreview([]);
    return subscribeToJob(jobId, {
      onStatus: (s) => setJob(s),
      onPreview: (frames) => setPreview((prev) => [...prev, ...frames]),
      onEnd: (status, err) => {
        if (status === "done") router.push(`/report/${jobId}`);
        else setError(err ?? "Analysis failed.");
      },
      onError: (msg) => setError(msg),
    });
  }, [jobId, router]);

  const start = useCallback(async (file: File) => {
    setError(null);
    setLocalFile(file);
    setPreview([]);

    // Track on this device first. The same analysis takes 88s on a laptop and 302s on the
    // server's shared vCPUs, and the video never has to leave the machine. Falls back to
    // uploading the file if the browser cannot run the model.
    setTracking({ frame: 0, total: 0 });
    try {
      const result = await trackInBrowser(file, (p) => {
        setTracking({ frame: p.frame, total: p.total });
        if (p.landmarks) {
          setPreview((prev) => [...prev, { frame: p.frame, joints: p.landmarks! }]);
        }
      });
      setTracking(null);
      const created = await submitClientAnalysis(result);
      // The server has no copy of this video, so the report has to play it from here.
      rememberLocalVideo(created.job_id, file);
      setJob(created);
      return;
    } catch (e) {
      setTracking(null);
      console.warn("browser tracking unavailable, uploading instead:", e);
      setFellBack((e as Error).message);
    }

    setUploadPct(0);
    try {
      const created = await uploadVideo(file, (f) => setUploadPct(f));
      setUploadPct(null);
      setJob(created);
    } catch (e) {
      setUploadPct(null);
      setError((e as Error).message);
    }
  }, []);

  const busy =
    tracking !== null || uploadPct !== null || (job !== null && job.status !== "failed");

  return (
    <main className="wrap narrow">
      <div className="hero">
        <h2>Is your squat actually deep enough?</h2>
        <p>
          Upload a side-view video of a set. Squat&nbsp;Coach tracks your hips, knees, ankles and
          the barbell, then assesses every repetition against a strength-training reference text -
          citing the page behind each verdict.
        </p>
        <p className="faint">
          It also tells you plainly what a side view <em>cannot</em> judge, instead of guessing.
        </p>
      </div>

      {reqError && (
        <div className="notice bad">
          Could not reach the analysis service at the configured API URL ({reqError}). Start the
          backend with <code>uvicorn app.main:app --port 8000</code> from <code>backend/</code>.
        </div>
      )}

      {error && <div className="notice bad">{error}</div>}

      {fellBack && (
        <div className="notice warn">
          Could not run tracking in this browser, so the video is being uploaded and analysed on
          the server instead. Same verdicts, but slower. Reason: {fellBack}
        </div>
      )}

      {!busy && (
        <>
          <div
            className={`drop${over ? " over" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) start(f);
            }}
          >
            <strong>Drop a squat video here</strong>
            <span className="muted">or click to choose a file</span>
            <input
              ref={inputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) start(f);
              }}
            />
          </div>

          {reqs && (
            <>
              <h2>Before you record</h2>
              <div className="card">
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {reqs.recording.map((r) => (
                    <li key={r} className="muted" style={{ marginBottom: 5 }}>
                      {r}
                    </li>
                  ))}
                </ul>
                <p className="faint" style={{ marginTop: 12, marginBottom: 0 }}>
                  {reqs.formats.map((f) => f.toUpperCase()).join(", ")} · up to{" "}
                  {reqs.max_duration_s}s · at least {reqs.min_fps} fps and{" "}
                  {reqs.min_short_side_px}px on the short side · max {reqs.max_upload_mb} MB
                </p>
              </div>

              <h2>What a side view can and cannot judge</h2>
              <div className="card">
                <table>
                  <thead>
                    <tr>
                      <th>Criterion</th>
                      <th>From a side view</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reqs.coverage.map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}</td>
                        <td>
                          <span
                            className={`verdict-badge ${
                              c.assessable === "full"
                                ? "v-meets_standard"
                                : c.assessable === "partial"
                                  ? "v-cannot_assess"
                                  : "v-does_not_meet_standard"
                            }`}
                          >
                            {c.assessable === "full"
                              ? "yes"
                              : c.assessable === "partial"
                                ? "partial"
                                : "no"}
                          </span>
                        </td>
                        <td className="faint">{c.citation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="faint" style={{ marginTop: 12, marginBottom: 0 }}>
                  Three of the reference text&rsquo;s own eight headline faults - knees-out, stance
                  and rack height - are invisible to a sagittal camera. Squat&nbsp;Coach reports
                  them as <em>cannot assess</em> rather than guessing.
                </p>
              </div>
            </>
          )}
        </>
      )}

      {tracking !== null && (
        <div className="card">
          <h3>Tracking on this device</h3>
          <div className="bar">
            <i
              style={{
                width: `${tracking.total ? Math.round((tracking.frame / tracking.total) * 100) : 3}%`,
              }}
            />
          </div>
          <p className="faint" style={{ marginTop: 8, marginBottom: 0 }}>
            {tracking.total
              ? `Frame ${tracking.frame + 1} of ${tracking.total}`
              : "Loading the pose model..."}
            . This runs on your machine, so your video is not uploaded. Only landmark
            coordinates and a few small frames are sent.
          </p>
          <LiveTracking frames={preview} file={localFile} />
        </div>
      )}

      {uploadPct !== null && (
        <div className="card">
          <h3>Uploading</h3>
          <div className="bar">
            <i style={{ width: `${Math.round(uploadPct * 100)}%` }} />
          </div>
          <p className="faint" style={{ marginTop: 8, marginBottom: 0 }}>
            {Math.round(uploadPct * 100)}%
          </p>
        </div>
      )}

      {job && job.status !== "failed" && (
        <div className="card">
          <h3>Analysing {job.filename}</h3>
          <div className="bar">
            <i style={{ width: `${Math.round(job.progress * 100)}%` }} />
          </div>
          <ul className="stages">
            {STAGE_ORDER.map((s) => {
              const current = STAGE_ORDER.indexOf(job.stage);
              const mine = STAGE_ORDER.indexOf(s);
              const cls = mine < current ? "done" : mine === current ? "active" : "";
              return (
                <li key={s} className={cls}>
                  <span className="dot" />
                  {s}
                </li>
              );
            })}
          </ul>
          <p className="faint" style={{ marginTop: 10, marginBottom: 0 }}>
            Tracking runs on the CPU at roughly 7&times; the clip length, and writing the
            assessment adds about half a minute. An 8-second video takes around 90 seconds.
          </p>

          {job.stage === "Tracking the movement" && (
            <LiveTracking frames={preview} file={localFile} />
          )}
        </div>
      )}

      {job?.status === "failed" && (
        <button className="btn secondary" onClick={() => { setJob(null); setError(null); }}>
          Try another video
        </button>
      )}
    </main>
  );
}
