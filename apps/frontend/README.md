# PromptPilot Frontend

The Next.js frontend provides the persistent PromptPilot product workflow: authentication, projects, conversations, original requests, analysis, clarification, evidence and document status, context assembly, versioned prompt generation, target execution, and saved evaluation comparison.

Install workspace dependencies from the repository root with `pnpm install`, then run:

```powershell
pnpm --filter @promptpilot/frontend dev
```

The UI uses cookie-authenticated same-origin `/api/v1` routes. During local development, Next.js proxies them to `http://localhost:8000`; set the server-only `BACKEND_ORIGIN` to change the origin. Production requires an HTTPS origin. Start the backend first and open `http://localhost:3000`.

Refresh and navigation recovery come from persisted backend records. Context previews are assembled on demand. Open **Models & API keys** from chat or the AI team tabs to enter a provider key, load its model catalog, and choose a default model. Keys are submitted through the authenticated same-origin API, encrypted on the backend, cleared from the input after saving, and never returned in API responses. The browser does not call providers directly. Server environment credentials remain a fallback. Evaluation is shown only for persisted runs, and a baseline/PromptPilot comparison requires one persisted `succeeded` run of each strategy.

**AI delivery team → Team models** shows every task’s provider and model assignment. The quick-start control fills unassigned tasks, and each task can use another model from the same key. The node inspector supports **Save and run** to persist edited settings before execution. **Output** and **Runs** show reviewable results and execution history.

With a connected model, clarification follows that model’s task-specific analysis and reconsiders the full saved question/answer history after each reply. Offline questions are labelled explicitly. **Recheck with selected model** upgrades an existing offline session while preserving its replies.

Run frontend checks from the repository root:

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @promptpilot/frontend build
```

The browser acceptance journey uses an isolated temporary SQLite database and a
local deterministic OpenAI-compatible fake provider. It does not call a live
provider. Install Chromium with `pnpm exec playwright install chromium`, then
run `pnpm test:e2e`. On Ubuntu, include system dependencies with
`pnpm exec playwright install --with-deps chromium`.
