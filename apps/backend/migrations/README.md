# Authentication Migration

For PostgreSQL:

```powershell
psql "$env:DATABASE_URL" -f apps/backend/migrations/001_users_and_sessions.sql
```

The migration is idempotent for development setup. A future Alembic environment should adopt this schema as its initial revision before additional tables are introduced. The test suite uses an isolated SQLite database for fast unit/integration tests; PostgreSQL compatibility is checked by the migration in CI.
