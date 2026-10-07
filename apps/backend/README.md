# PromptPilot Backend

The FastAPI backend implements the persistent product workflow, authentication, document ingestion, prompt execution, and evaluation.

Boundaries are API routes, application use cases, domain services, persistence, authentication, and future AI/document adapters.

Run locally:

```powershell
python -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
python -m uvicorn promptpilot_backend.main:app --reload --port 8000
```

The default development database is SQLite when `DATABASE_URL` is omitted. Production uses PostgreSQL through psycopg v3 and the checked-in Alembic migrations (`python -m alembic upgrade head`). ORM table creation is limited to development and test startup; production requires the migrated schema. Set `STORAGE_PATH` to a persistent writable directory in production.

Production settings validate the PostgreSQL URL, HTTPS CORS origins, absolute persistent storage, request limits, and all-or-none LLM configuration. LLM credentials are optional for startup. `/healthz` is a process check; `/readyz` verifies database connectivity. Registration and login share database-backed throttling: 20 attempts per normalized account identity per 15-minute window.

For Vercel/Render configuration, migration ordering, backups, and safe rollback guidance, see [the production deployment guide](../../docs/production-deployment.md).

## Guarded benchmark pricing

Live benchmark adapters require an offline-loaded provider pricing snapshot. The protocol's
`monetary_budget.pricing_snapshot_reference` must pin the canonical snapshot content as
`sha256:<64 lowercase hex characters>`. The snapshot records its HTTPS source, capture and
expiry timestamps, budget currency, all-in input/output prices per million tokens, and the
provider-enforced maximum context size for every provider/model assignment used by analysis,
question generation, prompt generation, target execution, and judging.

The estimator reserves the full context window at both published token rates for each call.
This deliberately conservative upper bound is validated before ledger reservation; missing,
expired, mismatched, unsupported, or invalid pricing blocks execution. Pricing is never fetched
from a mutable endpoint at runtime. A human must verify that the pinned source data is accurate
and covers all charges before issuing any external live-study authorization.

The live adapter's provider name and model are read from `LLM_PROVIDER` and `LLM_MODEL` at
runtime and must match every frozen provider-role assignment. The endpoint must be HTTPS, and
`LLM_API_KEY` is used only to authenticate runtime provider requests; it is not part of protocol,
pricing, ledger, or evidence data.

The offline `launch-gate` command can validate a supplied snapshot with `--pricing-snapshot`.
It does not make provider calls or create authorization, and it can report technical readiness
only: the report never authorizes live execution because software cannot authenticate human
authorization or consent. Offline validation and dry-run commands remain planning-only and report
zero network calls and zero cost estimate; these are not live price quotes.
