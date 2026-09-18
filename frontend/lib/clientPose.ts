import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";
import { API } from "./api";

/**
 * Run pose tracking on the user's own machine.
 *
 * The same image that tracks the common sample in 88s on a developer laptop takes 302s on Cloud
 * Run, and that is not fixable by configuration: the container correctly reports 4 CPUs and uses
 * 4 threads, and raising the vCPU allocation made throughput worse. Shared vCPUs are just slower
 * per core.
 *
 * So the expensive part moves to hardware that is already fast. Only pose moves. The landmarks
 * go to the server, which runs the same measurement code it always did, so the verdicts stay
 * comparable with the verified build rather than becoming a second implementation's opinion.
 *
 * Barbell detection still needs pixels, so a decimated set of frames is uploaded with them.
 */

const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task";

// Pinned to the installed package version so the WASM and the JS cannot drift apart.
const WASM_BASE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";

// Landmarks the server needs: everything the measurement layer reads, for BOTH sides, so the
// server still decides which side faces the camera. Must match CLIENT_LANDMARK_INDICES.
const SEND_INDICES = [0, 7, 8, 11, 12, 13, 14, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32];

// One frame in five carries an image for barbell detection. The server interpolates bar
// positions between detections up to ten frames apart, so this keeps every repetition bracketed
// by real measurements.
const FRAME_IMAGE_STRIDE = 5;
const UPLOAD_MAX_WIDTH = 720;   // enough for plate detection, small enough to upload
const JPEG_QUALITY = 0.72;

export interface LandmarkFrame {
  i: number;
  lm: Record<string, [number, number, number]>;
}

export interface ClientTrackResult {
  payload: {
    video: {
      filename: string;
      width: number;
      height: number;
      fps: number;
      duration_s: number;
      frame_count: number;
    };
    frames: LandmarkFrame[];
  };
  images: { index: number; blob: Blob }[];
}

export interface TrackProgress {
  frame: number;
  total: number;
  landmarks: Record<string, [number, number, number]> | null;
}

let landmarkerPromise: Promise<PoseLandmarker> | null = null;

async function getLandmarker(): Promise<PoseLandmarker> {
  if (!landmarkerPromise) {
    landmarkerPromise = (async () => {
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
      return PoseLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numPoses: 1,
        minPoseDetectionConfidence: 0.5,
        minPosePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
      });
    })().catch((e) => {
      landmarkerPromise = null;
      throw e;
    });
  }
  return landmarkerPromise;
}

/** Decode a local file frame by frame and run pose on each. */
export async function trackInBrowser(
  file: File,
  onProgress?: (p: TrackProgress) => void,
  fpsHint = 30,
): Promise<ClientTrackResult> {
  const landmarker = await getLandmarker();

  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.src = url;
  video.muted = true;
  video.playsInline = true;

  await new Promise<void>((resolve, reject) => {
    video.onloadedmetadata = () => resolve();
    video.onerror = () => reject(new Error("The browser could not decode this video."));
  });

  const width = video.videoWidth;
  const height = video.videoHeight;
  const duration = video.duration;
  // No frame-rate API in the browser. 30fps covers the overwhelming majority of phone footage,
  // and the server derives timestamps from this, so a wrong guess shifts reported times rather
  // than changing any measurement.
  const fps = fpsHint;
  const total = Math.max(1, Math.floor(duration * fps));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Could not create a 2D canvas context.");

  // Smaller canvas for the uploaded JPEGs.
  const scale = Math.min(1, UPLOAD_MAX_WIDTH / width);
  const small = document.createElement("canvas");
  small.width = Math.round(width * scale);
  small.height = Math.round(height * scale);
  const smallCtx = small.getContext("2d");

  const frames: LandmarkFrame[] = [];
  const images: { index: number; blob: Blob }[] = [];

  const seekTo = (t: number) =>
    new Promise<void>((resolve) => {
      const done = () => {
        video.removeEventListener("seeked", done);
        resolve();
      };
      video.addEventListener("seeked", done);
      video.currentTime = Math.min(t, Math.max(0, duration - 1e-3));
    });

  try {
    for (let i = 0; i < total; i++) {
      await seekTo(i / fps);
      ctx.drawImage(video, 0, 0, width, height);

      const res = landmarker.detectForVideo(canvas, Math.round((i * 1000) / fps));
      const entry: LandmarkFrame = { i, lm: {} };
      const pts = res.landmarks?.[0];
      if (pts) {
        for (const idx of SEND_INDICES) {
          const p = pts[idx];
          if (!p) continue;
          entry.lm[String(idx)] = [
            Number(p.x.toFixed(5)),
            Number(p.y.toFixed(5)),
            Number((p.visibility ?? 0).toFixed(3)),
          ];
        }
      }
      frames.push(entry);
      onProgress?.({ frame: i, total, landmarks: pts ? entry.lm : null });

      if (i % FRAME_IMAGE_STRIDE === 0 && smallCtx) {
        smallCtx.drawImage(canvas, 0, 0, small.width, small.height);
        const blob = await new Promise<Blob | null>((resolve) =>
          small.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
        );
        if (blob) images.push({ index: i, blob });
      }
    }
  } finally {
    URL.revokeObjectURL(url);
  }

  return {
    payload: {
      video: {
        filename: file.name,
        // The server scales normalised landmarks by these, and detects the plate in the
        // uploaded images, so the dimensions sent must match the images that were sent.
        width: small.width,
        height: small.height,
        fps,
        duration_s: duration,
        frame_count: total,
      },
      frames,
    },
    images,
  };
}

// BlazePose indices for the left chain, used only to draw the live view while tracking runs.
// The server still decides which side actually faces the camera; this is a progress view, not
// evidence, exactly as the server-side preview was.
const DISPLAY_JOINTS: Record<string, number> = {
  shoulder: 11,
  hip: 23,
  knee: 25,
  ankle: 27,
  heel: 29,
  toe: 31,
};

/** Convert a landmark frame into the shape the live view already knows how to draw. */
export function toPreviewFrame(entry: LandmarkFrame) {
  const joints: Record<string, [number, number, number]> = {};
  for (const [name, idx] of Object.entries(DISPLAY_JOINTS)) {
    const v = entry.lm[String(idx)];
    if (v) joints[name] = v;
  }
  return { frame: entry.i, joints };
}

/** Send landmarks and the decimated frames, and return the created job. */
export async function submitClientAnalysis(result: ClientTrackResult) {
  const form = new FormData();
  form.append("payload", JSON.stringify(result.payload));
  for (const { index, blob } of result.images) {
    form.append("frames", blob, `${index}.jpg`);
  }
  const r = await fetch(`${API}/analyses`, { method: "POST", body: form });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return r.json();
}
