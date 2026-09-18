/**
 * Keep a viewed report readable after the backend has forgotten it.
 *
 * Job state on the server is an in-memory map and Cloud Run scales to zero, so the report and
 * overlay behind a given job id stop existing once the instance goes away. Reloading the page, or
 * coming back to an open tab after a coffee, then produced a bare error on a report the user had
 * already been shown.
 *
 * The honest fix would be persisting reports server-side, which is the database decision recorded
 * in BUILD_NOTES as out of scope. This is the cheap 90%: the browser keeps what it was already
 * given, so a reload works. It deliberately does NOT make the link shareable or durable across
 * devices, and the UI says so when it falls back, rather than implying the server still has it.
 */

import type { Overlay, Report } from "./types";

const KEY = (jobId: string) => `squat-coach:report:${jobId}`;

export type CachedReport = { report: Report; overlay: Overlay; savedAt: number };

export function cacheReport(jobId: string, report: Report, overlay: Overlay): void {
  if (typeof window === "undefined") return;
  try {
    const payload: CachedReport = { report, overlay, savedAt: Date.now() };
    window.sessionStorage.setItem(KEY(jobId), JSON.stringify(payload));
  } catch {
    // Quota, private browsing, or a disabled store. An overlay carries one entry per frame, so a
    // long clip can exceed the session quota. Failing to cache must never break the live report,
    // which is already rendered from the network response by the time this runs.
  }
}

export function cachedReport(jobId: string): CachedReport | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY(jobId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedReport;
    // Guard against a half-written or older-shaped entry rather than crashing the page on it.
    if (!parsed?.report?.findings || !parsed?.overlay?.frames) return null;
    return parsed;
  } catch {
    return null;
  }
}
