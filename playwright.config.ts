import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { defineConfig } from "@playwright/test";

const tempDirectory =
  process.env.PROMPTPILOT_ACCEPTANCE_TEMP ??
  mkdtempSync(join(tmpdir(), "promptpilot-acceptance-"));

const python = process.env.PYTHON ?? resolve(".venv", "Scripts", "python.exe");
const databasePath = join(tempDirectory, "acceptance.db").replaceAll("\\", "/");

export default defineConfig({
  testDir: "./tests/acceptance",
  testMatch: "**/*.e2e.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:8131",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node tests/acceptance/fake-openai-provider.mjs",
      url: "http://127.0.0.1:8132/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: { PROMPTPILOT_FAKE_PROVIDER_PORT: "8132" },
    },
    {
      command: `"${python}" -m uvicorn promptpilot_backend.main:app --host 127.0.0.1 --port 8130`,
      cwd: "./apps/backend",
      url: "http://127.0.0.1:8130/docs",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        DATABASE_URL: `sqlite:///${databasePath}`,
        SESSION_COOKIE_NAME: "promptpilot_acceptance_session",
        CORS_ORIGINS: "http://127.0.0.1:8131",
        PYTHONPATH: "src",
        LLM_PROVIDER: "local-acceptance-fake",
        LLM_BASE_URL: "http://127.0.0.1:8132/v1",
        LLM_MODEL: "acceptance-model",
        LLM_API_KEY: "acceptance-only",
        LLM_TIMEOUT: "5",
      },
    },
    {
      command:
        "pnpm --filter @promptpilot/frontend exec next dev --hostname 127.0.0.1 --port 8131",
      url: "http://127.0.0.1:8131/register",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8130",
      },
    },
  ],
});
