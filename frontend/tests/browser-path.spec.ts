import { test, expect } from "@playwright/test";
import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";

/**
 * Does the browser-WASM path produce the verdicts the verified build produces?
 *
 * This is the gap the Python tests cannot reach. `scripts/test_client_path.py` replays landmarks
 * from *native* MediaPipe; production compiles the same model to WASM and may hand it to a GPU
 * delegate. This test uploads a real video to a real browser and compares the verdicts that come
 * back against the server-path baseline committed in EVIDENCE.
 *
 * It also asserts the page actually rendered. A previous bug streamed landmarks back correctly and
 * painted nothing: TypeScript passed, the endpoint test passed, the end-to-end script passed, and
 * the feature was broken because no check ever opened the page.
 */

const API = "http://127.0.0.1:8100";
const REPO = path.resolve(__dirname, "..", "..");
const VIDEO = path.join(REPO, "EVIDENCE", "common-sample", "common_sample.mp4");
const BASELINE = path.join(REPO, "EVIDENCE", "common-sample", "report.json");

type Finding = {
  rep_index: number;
  criterion_id: string;
  verdict: string;
  measurement?: { value?: number | null } | null;
};

function verdictMap(findings: Finding[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of findings) out[`rep${f.rep_index}.${f.criterion_id}`] = f.verdict;
  return out;
}

function valueMap(findings: Finding[]): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const f of findings) {
    const v = f.measurement?.value;
    out[`rep${f.rep_index}.${f.criterion_id}`] = typeof v === "number" ? v : null;
  }
  return out;
}

test("the browser tracks the movement and reproduces the verified verdicts", async ({ page }) => {
  expect(existsSync(VIDEO), `missing test clip: ${VIDEO}`).toBe(true);
  expect(existsSync(BASELINE), `missing baseline: ${BASELINE}`).toBe(true);

  // Surface browser-side failures instead of letting them present as a timeout. MediaPipe loads
  // its WASM bundle over the network, and a failure there is silent from the DOM's point of view.
  const consoleErrors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();

  // The file input is intentionally hidden behind a drop zone, so set files on it directly.
  await page.locator('input[type="file"]').setInputFiles(VIDEO);

  // The browser now decodes every frame and runs pose on it. Navigation to the report is the
  // signal that the whole flow finished: track, upload, assess, redirect.
  //
  // Headless Chromium has no GPU delegate, so the WASM build runs pose on the CPU and this is
  // considerably slower than the same clip in a real browser. Generous, because a timeout here
  // says nothing about correctness. Note also that editing frontend sources while this runs will
  // fail it for an unrelated reason: Next hot-reloads, the page component remounts, and the SSE
  // subscription that fires the redirect is lost.
  await page.waitForURL(/\/report\/[0-9a-f]+/, { timeout: 15 * 60 * 1000 });
  expect(consoleErrors, `browser console errors:\n${consoleErrors.join("\n")}`).toEqual([]);

  const jobId = page.url().split("/report/")[1];
  expect(jobId).toBeTruthy();

  // The page rendered something a human would recognise as a report.
  await expect(page.locator(".verdict-badge").first()).toBeVisible();

  // Now compare what the browser's own landmarks produced against the committed baseline.
  const res = await page.request.get(`${API}/jobs/${jobId}/report`);
  expect(res.ok(), `report fetch failed: ${res.status()}`).toBe(true);
  const live = await res.json();
  const base = JSON.parse(readFileSync(BASELINE, "utf-8"));

  // Keep the browser's own report. Each run costs about eight minutes of CPU-bound WASM pose, and
  // the job is gone from the server's in-memory map the moment the run ends, so a failure that
  // prints only the verdict that moved forces another full run to ask why. Dumped unconditionally:
  // the passing report is the thing to diff against when it next stops passing.
  const dump = path.join(__dirname, "..", "test-results", "browser-report.json");
  mkdirSync(path.dirname(dump), { recursive: true });
  writeFileSync(
    dump,
    JSON.stringify(
      {
        reps: live.reps,
        pose: live.pose,
        bar: live.bar,
        quality: live.quality,
        findings: live.findings.map((f: Finding & { measurement?: unknown }) => ({
          rep_index: f.rep_index,
          criterion_id: f.criterion_id,
          verdict: f.verdict,
          measurement: f.measurement,
        })),
      },
      null,
      2,
    ),
    "utf-8",
  );
  console.log(`browser report written to ${dump}`);

  const liveV = verdictMap(live.findings);
  const baseV = verdictMap(base.findings);

  expect(Object.keys(liveV).length, "finding count differs from the baseline")
    .toBe(Object.keys(baseV).length);

  // Report every divergence at once. Verdicts are the product; a single mismatch matters, and
  // seeing all of them together says whether it is one borderline criterion or a systemic shift.
  const moved = Object.keys(baseV)
    .filter((k) => baseV[k] !== liveV[k])
    .map((k) => {
      const lv = valueMap(live.findings)[k];
      const bv = valueMap(base.findings)[k];
      return `${k}: ${baseV[k]} (${bv}) -> ${liveV[k]} (${lv})`;
    });

  expect(
    moved,
    `The real browser produced different verdicts than the verified server path.\n` +
      `This is the divergence scripts/test_client_path.py cannot detect, because it uses\n` +
      `native MediaPipe rather than the WASM build.\n\n${moved.join("\n")}`,
  ).toEqual([]);
});
