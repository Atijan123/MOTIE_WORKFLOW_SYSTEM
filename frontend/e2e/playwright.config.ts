// The browser walk-throughs. Run them with
//   docker compose run --rm e2e
// against the running dev stack (`docker compose up -d`), on the DEV database
// only: they log in as the seeded dev users and create real cases.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  // One browser at a time: the steps hand one case from person to person.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  // `next dev` compiles each page the first time it's opened, which can take
  // a while on a Windows bind mount.
  timeout: 10 * 60_000,
  expect: { timeout: 30_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3001",
    navigationTimeout: 120_000,
    actionTimeout: 60_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
