# Authentication Migration

For PostgreSQL:

```powershell
psql "$env:DATABASE_URL" -f apps/backend/migrations/001_users_and_sessions.sql
```

The migration is idempotent for development setup. A future Alembic environment should adopt this schema as its initial revision before additional tables are introduced. The test suite uses an isolated SQLite database for fast unit/integration tests; PostgreSQL compatibility is checked by the migration in CI.

Project slice migration order:

```powershell
psql "$env:DATABASE_URL" -f apps/backend/migrations/001_users_and_sessions.sql
psql "$env:DATABASE_URL" -f apps/backend/migrations/002_projects_and_memberships.sql
psql "$env:DATABASE_URL" -f apps/backend/migrations/003_conversations_and_messages.sql
```

Projects use archive status instead of deletion. The owner membership is explicit and is created in the same transaction as its project.

Messages use a per-conversation `sequence` for deterministic ordering. Clients may send `Idempotency-Key`; a repeated key in the same conversation returns the original message instead of inserting a duplicate.
