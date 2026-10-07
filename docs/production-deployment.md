# Production deployment readiness

PromptPilot is prepared for a Vercel Next.js frontend and a Render FastAPI
service backed by Render PostgreSQL and a persistent document disk. This
repository change does not create accounts, provision resources, deploy the
application, or configure provider credentials. Applying `render.yaml` creates
billable resources; do not apply it without explicit approval.

## Topology and configuration

- Import the repository as a Vercel monorepo project with Framework Preset
  **Next.js** and Root Directory `apps/frontend`. Keep source files outside the
  Root Directory included so Vercel can use the root workspace lockfile.
- Use Node.js `22.x` and pnpm `10.34.6` (pinned by the root `packageManager`
  field). Set the Install Command to `pnpm install --frozen-lockfile` and the
  Build Command to `pnpm build`. Keep the framework-default `.next` output;
  Vercel manages the production start/runtime, so do not set a custom Start
  Command. `pnpm start` is only the equivalent self-hosted start command.
- Configure the server-only Vercel environment variable
  `BACKEND_ORIGIN=https://<your-render-service>.onrender.com` for every deployed
  environment. It must be an HTTPS origin with no path, credentials, query, or
  fragment. Never expose it as a `NEXT_PUBLIC_*` variable.
- `apps/frontend/next.config.ts` proxies only `/api/v1/:path*` to that fixed
  origin and sets `Cache-Control: no-store` on API responses. Browser API calls
  remain same-origin and retain their session cookies.
- Review `render.yaml` and set `CORS_ORIGINS` to the exact HTTPS frontend
  origins before provisioning. The Render pre-deploy command applies Alembic
  migrations. The service stores uploads under `/var/data/promptpilot` on its
  persistent disk.
- The Blueprint uses Render's current `0.1c-256mb` PostgreSQL and
  `0.5c-512mb` web-service plan IDs, the native `python` runtime, a 1 GB
  persistent disk, and the database `connectionString` reference. These are
  billable resources even though this change does not provision them.
- Render's PostgreSQL URL is normalized to psycopg v3 by the backend. Keep the
  database and persistent disk in the same region.

The Render Blueprint uses paid PostgreSQL, web-service, and disk resources.
Provisioning and public deployment are intentionally outside this change and
require explicit approval. Use the provider dashboard to configure secrets;
never commit credentials or put them in Vercel client-visible variables.

## Required backend settings

`APP_ENV=production`, `DATABASE_URL` (Render's PostgreSQL connection string),
`CORS_ORIGINS` (comma-separated HTTPS origins), and an absolute writable
`STORAGE_PATH` are required. `SESSION_COOKIE_NAME` and
`SESSION_TTL_SECONDS` have safe defaults; cookies are HTTP-only, SameSite=Lax,
and secure in production. Numeric upload, timeout, and redirect limits are
validated at startup.

LLM configuration is optional for startup. If used, configure
`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` together in the
backend's secret store. Do not configure a provider in CI or use frontend
environment variables for credentials.

## Database and release procedure

1. Provision Render resources only after approving their costs and regions.
2. Set the required backend and Vercel environment variables in their
   respective dashboards.
3. Deploy. Render runs `python -m alembic upgrade head` before starting the web
   service. The backend never creates production tables from ORM metadata.
4. Verify `/healthz` and database-backed `/readyz`, then verify registration,
   login/logout, project creation, and document persistence through the Vercel
   origin.
5. Back up PostgreSQL and the persistent disk independently. A document's
   parsed content is in PostgreSQL while original uploaded bytes are on disk.

The initial migration is reviewed and checked in. Do not use `alembic downgrade`
as a production rollback: the initial downgrade drops application data. Prefer
rolling back the application release while preserving the database, and restore
backups only through the normal incident process.

## Local verification

```powershell
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm test
pnpm --filter @promptpilot/frontend build
pnpm test:e2e
cd apps/backend
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m mypy --strict src
```

The browser acceptance test uses an isolated SQLite database and a deterministic
loopback-only fake OpenAI-compatible provider. It never calls a live or paid
provider. PostgreSQL migration and production-install checks run in GitHub
Actions.
