# PromptPilot Backend

The backend now contains the authentication foundation. It remains intentionally limited to identity and session behavior; project and AI features are future vertical slices.

Boundaries are API routes, application use cases, domain services, persistence, authentication, and future AI/document adapters.

Run locally:

```powershell
python -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
python -m uvicorn promptpilot_backend.main:app --reload --port 8000
```

The default development database is SQLite when `DATABASE_URL` is omitted. Production and integration environments should use PostgreSQL.
