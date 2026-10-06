import { spawn } from "node:child_process";
import {
  copyFileSync,
  createWriteStream,
  mkdirSync,
  mkdtempSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const tempDirectory = mkdtempSync(join(tmpdir(), "promptpilot-acceptance-"));
const serverLog = join(tempDirectory, "acceptance-server.log");
let exitCode = 1;

try {
  const logFile = createWriteStream(serverLog);
  const child = spawn(
    "pnpm",
    ["exec", "playwright", "test", "--config=playwright.config.ts"],
    {
      cwd: process.cwd(),
      env: {
        ...process.env,
        PROMPTPILOT_ACCEPTANCE_TEMP: tempDirectory,
      },
      shell: process.platform === "win32",
      stdio: ["inherit", "pipe", "pipe"],
    },
  );

  child.stdout.pipe(process.stdout);
  child.stdout.pipe(logFile);
  child.stderr.pipe(process.stderr);
  child.stderr.pipe(logFile);

  let spawnError;
  child.once("error", (error) => {
    spawnError = error;
  });
  exitCode = await new Promise((resolve) => {
    child.once("close", (code) => resolve(code ?? 1));
  });
  await new Promise((resolve) => logFile.end(resolve));
  if (spawnError) throw spawnError;
} finally {
  if (exitCode !== 0) {
    mkdirSync("test-results", { recursive: true });
    copyFileSync(serverLog, join("test-results", "acceptance-server.log"));
  }
  rmSync(tempDirectory, { recursive: true, force: true });
}

process.exitCode = exitCode;
