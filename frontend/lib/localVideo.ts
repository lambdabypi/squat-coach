/**
 * Hold the user's own file so the report can play it without it ever being uploaded.
 *
 * On the browser-tracking path the server never receives the video, only landmarks and a few
 * small frames. The report page was still asking the backend for `/jobs/{id}/video`, which does
 * not exist on that path, so the player had no source: the container collapsed and the overlay
 * drew its skeleton into a 300x150 box. The analysis was fine; the evidence was invisible.
 *
 * A module-level map survives client-side navigation, which is how we get from the upload page
 * to the report. It does not survive a reload, so the report falls back to asking the server -
 * correct for the upload path, and a clear "video not available" state for a reloaded
 * browser-tracked report.
 */

const files = new Map<string, { file: File; url: string }>();

export function rememberLocalVideo(jobId: string, file: File): void {
  const existing = files.get(jobId);
  if (existing) URL.revokeObjectURL(existing.url);
  files.set(jobId, { file, url: URL.createObjectURL(file) });
}

export function localVideoUrl(jobId: string): string | null {
  return files.get(jobId)?.url ?? null;
}

export function hasLocalVideo(jobId: string): boolean {
  return files.has(jobId);
}
