# PromptPilot

PromptPilot is an AI context-engineering and prompt-generation workspace built as a university Final Year Project. The product persists projects, conversations, request analysis, clarification answers, project evidence, versioned prompts, model runs, and evaluations.

## Local product workflow

Requirements: Python 3.12+, Node.js, and pnpm.

```powershell
pnpm install
cd apps/backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn promptpilot_backend.main:app --reload --port 8000
```

In a second terminal, from the repository root:

```powershell
pnpm --filter @promptpilot/frontend dev
```

Open `http://localhost:3000`, register or sign in, create a project and conversation, then follow the eight workspace stages: Request, Analysis, Clarify, Evidence, Context, Generated prompt, Execution, and Evaluation. The frontend expects the API at `http://localhost:8000`; set `NEXT_PUBLIC_API_BASE_URL` to override it.

Analysis and clarification have deterministic offline paths. Prompt generation and target-model execution require server-side provider configuration (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`). When unavailable, the UI reports that state and does not manufacture a model response. Credentials are never entered in the browser. Heuristic evaluation can compare compatible persisted runs without a judge provider; an LLM-judge method requires its configured provider.

## Verification

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @promptpilot/frontend build
cd apps/backend
..\..\.venv\Scripts\python.exe -m pytest
..\..\.venv\Scripts\python.exe -m ruff check src tests
..\..\.venv\Scripts\python.exe -m mypy --strict src
```

Product functionality and research evidence are separate. A working product flow does not establish that PromptPilot improves model responses. The guarded benchmark and live-study code has additional frozen protocols, approval boundaries, call ceilings, and provenance requirements; ordinary product use does not authorize or run a study.
