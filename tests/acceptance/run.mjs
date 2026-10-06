import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const tempDirectory = mkdtempSync(join(tmpdir(), "promptpilot-acceptance-"));
let exitCode = 1;

try {
  const result = spawnSync(
    "pnpm",
    ["exec", "playwright", "test", "--config=playwright.config.ts"],
    {
      cwd: process.cwd(),
      env: {
        ...process.env,
        PROMPTPILOT_ACCEPTANCE_TEMP: tempDirectory,
      },
      shell: process.platform === "win32",
      stdio: "inherit",
    },
  );

  if (result.error) throw result.error;
  exitCode = result.status ?? 1;
} finally {
  rmSync(tempDirectory, { recursive: true, force: true });
}

process.exitCode = exitCode;
