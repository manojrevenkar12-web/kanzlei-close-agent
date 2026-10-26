import { defineConfig, devices } from "@playwright/test";

// Runs against a seeded stack: the API with KANZLEI_DEMO_MODE=true and `npm run preview`.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env["CI"] ? 1 : 0,
  reporter: process.env["CI"] ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env["E2E_BASE_URL"] ?? "http://localhost:4173",
    trace: "retain-on-failure",
    locale: "de-DE",
    // A machine with a browser installed outside Playwright's cache can point to it.
    launchOptions: process.env["PW_CHROMIUM_PATH"] ? { executablePath: process.env["PW_CHROMIUM_PATH"] } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
