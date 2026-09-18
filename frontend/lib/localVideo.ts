/**
 * Hold the user's own file so the report can play it without it ever being uploaded.
 *
 * On the browser-tracking path the server never receives the video, only landmarks and a few
 * small frames. The report page was still asking the backend for `/jobs/{id}/video`, which does
 * not exist on that path, so the player had no source: the container collapsed and the overlay
 * drew its skeleton into a 300x150 box. The analysis was fine; the evidence was invisible.
 *
 * A module-level map survives client-side navigation, which is how we get from the upload page to
 * the report. It does not survive a reload, and the fallback to the server 404s on this path, so
 * reloading a report used to lose the video even while the verdicts were still there. The blob is
 * therefore also written to IndexedDB (see `videoStore.ts`) and restored on demand.
 */

import { getVideo, putVideo } from "./videoStore";

const files = new Map<string, { blob: Blob; url: string }>();

export function rememberLocalVideo(jobId: string, file: File): void {
  const existing = files.get(jobId);
  if (existing) URL.revokeObjectURL(existing.url);
  files.set(jobId, { blob: file, url: URL.createObjectURL(file) });
  // Deliberately not awaited. Writing tens of megabytes must not delay the redirect to the
  // report, and a failure to persist is not a failure to analyse.
  void putVideo(jobId, file);
}

export function localVideoUrl(jobId: string): string | null {
  return files.get(jobId)?.url ?? null;
}

export function hasLocalVideo(jobId: string): boolean {
  return files.has(jobId);
}

/**
 * The in-memory URL if this session still has it, otherwise rehydrate from IndexedDB.
 *
 * Returns null when the video is genuinely gone - a different browser, cleared storage, or evicted
 * as one of the older entries - so the caller can say so instead of pointing a player at a 404.
 */
export async function restoreLocalVideo(jobId: string): Promise<string | null> {
  const hit = files.get(jobId);
  if (hit) return hit.url;
  const blob = await getVideo(jobId);
  if (!blob) return null;
  const url = URL.createObjectURL(blob);
  files.set(jobId, { blob, url });
  return url;
}
