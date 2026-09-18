import { defineConfig } from "@playwright/test";

/**
 * The one test that runs the real thing.
 *
 * Every other check in this project drives Python. `scripts/test_client_path.py` proves the
 * client-landmark path reproduces the server path's verdicts, but it generates the landmarks with
 * *native* MediaPipe, and production runs the same model compiled to WASM in a browser. Those are
 * not bit-identical, and near a tolerance boundary the difference is enough to move a verdict.
 * The browser path is also what every user actually hits.
 *
 * So this starts both services, opens a real Chromium, uploads a real video, and lets the browser
 * do the pose estimation itself.
 */
export default defineConfig({
  testDir: "./tests",
  // Browser-side pose on a 236-frame clip takes tens of seconds, and the backend then runs bar
  // detection and the assessment. One generous timeout beats a flaky short one.
  timeout: 20 * 60 * 1000,
  expect: { timeout: 30 * 1000 },
  fullyParallel: false,
  workers: 1,
  // A pass here is a claim about correctness, so never let a retry launder a flake into a pass.
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    // The upload path reads a local file; nothing here needs a camera or microphone.
    permissions: [],
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // The project venv, not whatever python is on PATH: mediapipe and opencv live in it.
      command:
        process.platform === "win32"
          ? ".venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8100"
          : ".venv/bin/python -m uvicorn app.main:app --port 8100",
      cwd: "../backend",
      env: {
        PYTHONPATH: ".",
        // Deliberately no ANTHROPIC_API_KEY. The rule engine produces every verdict without one,
        // and the model's narration is sampled at temperature 1.0, which would make the page
        // text differ between runs for no reason this test cares about.
        ALLOWED_ORIGINS: "http://127.0.0.1:3100,http://localhost:3100",
      },
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: !process.env.CI,
      timeout: 180 * 1000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // Ports 3100/8100 rather than 3000/8000 so this never fights a dev server you left running.
      command: "npm run dev -- -p 3100",
      cwd: ".",
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:8100" },
      url: "http://127.0.0.1:3100",
      reuseExistingServer: !process.env.CI,
      timeout: 180 * 1000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
