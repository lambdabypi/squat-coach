import type { JobStatus, Overlay, Report, Requirements } from "./types";

// `??` only falls back on null/undefined, so a present-but-empty NEXT_PUBLIC_API_URL (which is
// exactly what an unfilled `.env` line produces) would survive it and leave every request
// pointing at a relative path. Treat empty as unset.
const CONFIGURED_API = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "");
export const API = CONFIGURED_API || "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getRequirements(): Promise<Requirements> {
  return json(await fetch(`${API}/requirements`, { cache: "no-store" }));
}

export function uploadVideo(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<JobStatus> {
  // XHR rather than fetch: we need real upload progress, which fetch does not expose.
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/videos`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let detail = `Upload failed (${xhr.status})`;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          /* keep the default */
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () =>
      reject(new Error("Could not reach the analysis service. Is the backend running?"));
    xhr.send(form);
  });
}

export async function getJob(id: string): Promise<JobStatus> {
  return json(await fetch(`${API}/jobs/${id}`, { cache: "no-store" }));
}

export async function getReport(id: string): Promise<Report> {
  return json(await fetch(`${API}/jobs/${id}/report`, { cache: "no-store" }));
}

export async function getOverlay(id: string): Promise<Overlay> {
  return json(await fetch(`${API}/jobs/${id}/overlay`, { cache: "no-store" }));
}

export function videoUrl(id: string): string {
  return `${API}/jobs/${id}/video`;
}

export interface PreviewFrame {
  frame: number;
  joints: Record<string, [number, number, number]>;
}

/**
 * Subscribe to job progress and landmark previews over one held-open connection.
 *
 * Replaces interval polling. On Cloud Run, CPU is allocated only while a request is being
 * processed, and a detached worker thread is not that: short polls would give the analysis
 * roughly a 1% duty cycle. A streaming response keeps the request in flight, so the instance
 * keeps its CPU for the whole analysis and is billed for exactly that window.
 *
 * Returns an unsubscribe function.
 */
export function subscribeToJob(
  jobId: string,
  handlers: {
    onStatus?: (s: JobStatus) => void;
    onPreview?: (frames: PreviewFrame[], total: number) => void;
    onEnd?: (status: string, error: string | null) => void;
    onError?: (message: string) => void;
  },
): () => void {
  const es = new EventSource(`${API}/jobs/${jobId}/events`);

  es.addEventListener("status", (e) => {
    handlers.onStatus?.(JSON.parse((e as MessageEvent).data));
  });
  es.addEventListener("preview", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    handlers.onPreview?.(d.frames, d.total);
  });
  es.addEventListener("end", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    handlers.onEnd?.(d.status, d.error ?? null);
    es.close();
  });
  // EventSource reconnects automatically, which is usually right. Here the server closes the
  // stream when the job ends, so a genuine transport failure is the only reason to surface this.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      handlers.onError?.("The connection to the analysis service was lost.");
    }
  };

  return () => es.close();
}
