# PromptPilot

PromptPilot improves prompts either directly inside ChatGPT, Claude, and Gemini through a browser extension or in its standalone chat-first web interface. It gives live prompt-quality feedback, recommends missing information conversationally, asks only useful clarification questions, and produces an improved prompt without changing the user's intent.

## Browser extension — fastest examiner demo

The extension needs no Render, Vercel, database, or local server.

1. Open `chrome://extensions` in Chrome or `edge://extensions` in Edge.
2. Enable **Developer mode**, select **Load unpacked**, and choose `apps/extension`.
3. Pin PromptPilot and open its toolbar popup.
4. Paste an OpenRouter API key and select **Save key**.
5. Open or reload ChatGPT, Claude, or Gemini and type a prompt.
6. Select the floating **Improve** button, answer any useful questions, then select **Replace prompt**.

PromptPilot shows the score while the user types and never sends the prompt automatically. See [the extension guide](apps/extension/README.md) for privacy and public-release notes.

## Local product workflow

Requirements: Python 3.12+, Node.js 22, and pnpm 10.34.6 (the pinned workspace package manager).
One-time setup from the repository root:

```powershell
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\backend[dev]"
```

The simplest Windows startup launches both services after checking that their
ports are free:

```powershell
.\scripts\start-local.ps1
```

Stop both recorded local process trees safely with:

```powershell
.\scripts\stop-local.ps1
```

Alternatively, start the backend from the repository root in the first terminal:

```powershell
cd apps/backend
$env:PYTHONPATH = "src"
..\..\.venv\Scripts\python.exe -m uvicorn promptpilot_backend.main:app --reload --port 8000
```

Start the frontend from the repository root in a second terminal:

```powershell
pnpm --filter @promptpilot/frontend dev
```

Open `http://localhost:3000`, register or sign in, and use the default PromptPilot workspace. Enter a request in the bottom composer; analysis, recommendations, clarifications, and the improved prompt appear in the chat. Next.js proxies same-origin `/api/v1` requests to `BACKEND_ORIGIN` (defaulting to `http://localhost:8000` during development).

When PromptPilot asks a question, select **Reply** to focus the bottom box. The
box shows **Replying to PromptPilot** and the exact question; **Send answer**
saves your reply to that question, not as a new prompt. A saved reply remains in
the chat after refresh. If a request is not confirmed, your text stays in the
box for a safe retry. If the model fails after saving, use **Retry generation**
(or **Generate improved prompt** after refresh); you do not need to retype any
saved answers. The extension similarly preserves its filled reply boxes after
a provider failure.

For OpenRouter-backed generation, set these variables in the terminal that will
start the backend or launcher. Read the key without echoing it or placing it in
a file:

```powershell
$env:LLM_PROVIDER = "openrouter"
$env:LLM_BASE_URL = "https://openrouter.ai/api/v1"
$env:LLM_MODEL = "deepseek/deepseek-v4-flash-0731:free"
$secret = Read-Host "OpenRouter API key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
Remove-Variable secret, pointer
```

The one-command launcher inherits these variables. Provider credentials remain
backend-only; do not prefix them with `NEXT_PUBLIC_`.

Analysis and clarification have deterministic offline paths. Prompt generation and target-model execution require server-side provider configuration (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`). When unavailable, the UI reports that state and does not manufacture a model response. Credentials are never entered in the browser. Heuristic evaluation can compare compatible persisted runs without a judge provider; an LLM-judge method requires its configured provider.

## Verification

```powershell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @promptpilot/frontend build
pnpm exec prettier --check .github/workflows/ci.yml README.md apps/frontend/README.md package.json playwright.config.ts tests/acceptance/run.mjs
pnpm exec playwright install chromium
pnpm test:e2e
# With the documented port-8000 and port-3000 servers already running:
pnpm test:e2e:local
cd apps/backend
..\..\.venv\Scripts\python.exe -m pytest
..\..\.venv\Scripts\python.exe -m ruff check src tests
..\..\.venv\Scripts\python.exe -m mypy --strict src
```

## Continuous integration

GitHub Actions runs frontend quality checks on pull requests targeting `main`,
pushes to `main`, and manual dispatches. It also installs the backend into a
clean Python 3.12 environment, runs its tests and static checks, and smoke-tests
the documented Uvicorn startup against a temporary SQLite database. The browser
job runs the persistent workflow acceptance test with its local deterministic
fake provider; it requires no credentials and makes no external provider calls.

To run the equivalent checks locally, use the verification commands above,
install Chromium with `pnpm exec playwright install chromium`, then run
`pnpm test:e2e`. On Ubuntu, include Playwright's system dependency installation
with `pnpm exec playwright install --with-deps chromium`.
The browser test creates and removes its own temporary database and captures
diagnostic artifacts under ignored Playwright output directories.

Product functionality and research evidence are separate. A working product flow does not establish that PromptPilot improves model responses. The guarded benchmark and live-study code has additional frozen protocols, approval boundaries, call ceilings, and provenance requirements; ordinary product use does not authorize or run a study.

See [the production deployment guide](docs/production-deployment.md) for the Vercel/Render topology, required settings, migration sequence, backup boundaries, and deployment safety notes.
