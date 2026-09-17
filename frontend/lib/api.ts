import type { JobStatus, Overlay, Report, Requirements } from "./types";

export const API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

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
