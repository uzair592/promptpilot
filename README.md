# PromptPilot

PromptPilot is an AI-powered context engineering and prompt optimization platform for a university Final Year Project.

## Current status

Phase 1 repository foundation. No product features are implemented yet.

See `docs/` for the project overview, architecture, coding standards, roadmap, and architecture decisions.

## Current Implementation Slice

Authentication and user management are implemented in `apps/backend` with Argon2 password hashing, opaque database-backed HTTP-only sessions, and a minimal Next.js login/register/dashboard shell. Project management and AI features remain future slices.

Run the backend locally:

```powershell
cd apps/backend
python -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
python -m uvicorn promptpilot_backend.main:app --reload --port 8000
```

Run the frontend locally from `apps/frontend` with `pnpm dev` after installing workspace dependencies. The development shell expects the API at `http://localhost:8000`.
