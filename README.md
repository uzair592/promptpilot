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

Analysis and clarification have deterministic offline paths. Prompt generation and target-model execution require server-side provider configuration (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`). When unavailable, the UI reports that state and does not manufacture a model response. Heuristic evaluation can compare compatible persisted runs without a judge provider; an LLM-judge method requires its configured provider.

## Multi-model AI delivery team

The delivery team is a visual workflow editor: drag nodes, pan or zoom the canvas,
select a node to edit its instructions and dependencies, and inspect its output
and execution history. Independent nodes can run together. Outputs require review;
approval, requests for changes, and review notes are saved with the task.
Use **New workflow** to generate an idea-specific plan with a connected model or
start with an editable template. **Add node** lets you extend the workflow.

**Model Vault** loads its provider catalog from the backend. It supports OpenRouter,
OpenAI, Anthropic, Gemini, xAI/Grok, DeepSeek, Mistral, Groq, and public HTTPS
OpenAI-compatible APIs through the Custom option. **Load available models** queries
your provider's current model catalog; you can also enter a model ID. Different
nodes can use different models from the same connection. Saved connections also
power the prompt-improvement chat through its **Chat model** selector.

Open a project and select **AI delivery team** in the sidebar. A project owner or
editor can connect OpenRouter, OpenAI, Anthropic, or Google Gemini, then turn a
product idea into ordered discovery, backend, frontend, testing, and release
milestones. PromptPilot recommends an available provider for each role, allows a
human to change the assignment, and runs a task only after **Run node** is
selected. The product manager, API, frontend, backend, and tester roles receive
the project goal and saved prerequisite handoffs. Frontend and backend can run
together after their prerequisites; **Run ready nodes** starts independent
model requests concurrently, and testing waits for both results. OpenRouter's `openrouter/free`
router is the default free starting
model; availability and rate limits are controlled by OpenRouter.

Provider keys are submitted over the same-origin authenticated API, encrypted
before database storage, masked in every response, and never sent back to the
browser. In local development, PromptPilot creates a stable vault key in
`STORAGE_PATH/.provider-vault.key` automatically. Keep that file with the local
database: deleting it makes saved connections unreadable. In production, set a
stable `PROVIDER_KEY_ENCRYPTION_KEY` before saving connections:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:PROVIDER_KEY_ENCRYPTION_KEY = "<generated value>"
```

Keep this key outside Git. Losing or changing it makes existing saved provider
connections and GitHub tokens unreadable. The generated prompt has a **Plan and
build this project** link that transfers its text into the AI team's plan form.
To connect GitHub, create a fine-grained GitHub token restricted to the chosen
repository with **Contents** and **Pull requests** write access. The project
owner enters `owner/repo` or a full repository URL such as
`https://github.com/uzair592/promptpilot` and the token in the AI team's GitHub form.
A profile URL such as `https://github.com/uzair592` lacks a repository name. The token
is encrypted on the backend and never returned to the browser. A code specialist
produces a JSON `files` draft. Review it, then select **Publish reviewed code to
GitHub** to create a task branch and draft pull request. The app fetches a
bounded source snapshot from the default branch; unmerged task outputs are
passed to downstream specialists through saved handoffs.

Scheduled times are durable planning records; no unattended worker is enabled.
The app does not run generated code, merge PRs, or deploy. Review every draft
and run tests before merging. The chat automatically uses your most recently
connected active model when no explicit connection is selected. Server-wide
`LLM_*` configuration remains available as a fallback when no vault connection
is active. Gemini and Anthropic use their native API formats. Transient provider
failures receive bounded retries; invalid JSON gets one repair attempt. Invalid
keys and missing models produce specific errors instead of an endless retry loop.

The quality meter is a completeness estimate. It evaluates newly typed prompts
independently of an earlier analysis. Greetings and reactions score zero and do
not start model calls. Clarification questions target the current task, omit
optional gaps, and stop after at most three questions. Current-message replies
take priority over other memory in the generation context.

Local startup upgrades existing SQLite provider/workflow tables automatically.
Production deployments must apply `python -m alembic upgrade head` before startup.

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
