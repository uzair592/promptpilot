import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(
  await readFile(resolve(root, "manifest.json"), "utf8"),
);
const requiredFiles = [
  manifest.background.service_worker,
  manifest.action.default_popup,
  ...manifest.content_scripts.flatMap((script) => script.js),
];

if (manifest.manifest_version !== 3)
  throw new Error("Extension must use Manifest V3.");
if (
  manifest.permissions.some(
    (permission) => permission === "tabs" || permission === "<all_urls>",
  )
) {
  throw new Error("Extension requests an unnecessarily broad permission.");
}
for (const filename of requiredFiles) await readFile(resolve(root, filename));

console.log(
  `PromptPilot extension manifest validated (${requiredFiles.length} runtime files).`,
);
