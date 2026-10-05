# PromptPilot Frontend

The Next.js frontend provides the persistent PromptPilot product workflow: authentication, projects, conversations, original requests, analysis, clarification, evidence and document status, context assembly, versioned prompt generation, target execution, and saved evaluation comparison.

Install workspace dependencies from the repository root with `pnpm install`, then run:

```powershell
pnpm --filter @promptpilot/frontend dev
```

The UI uses cookie-authenticated backend routes and defaults to `http://localhost:8000`. Override that address with `NEXT_PUBLIC_API_BASE_URL`. Start the backend first and open `http://localhost:3000`.

Refresh and navigation recovery come from persisted backend records. Context previews are assembled on demand. Prompt generation and live target execution show an unavailable state unless the backend has provider credentials; the frontend never accepts or exposes those credentials and never substitutes fake responses. Evaluation is shown only for persisted runs, and a baseline/PromptPilot comparison requires one completed run of each strategy.

Run frontend checks from the repository root:

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @promptpilot/frontend build
```
