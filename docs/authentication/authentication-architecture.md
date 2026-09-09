# Authentication Architecture

PromptPilot uses database-backed opaque sessions for browser authentication. Registration and login create a cryptographically random token; only its SHA-256 hash is stored in `sessions`. The raw token is sent only as an HTTP-only, `SameSite=Lax` cookie. Production cookies are `Secure` and use the configured name and TTL.

The backend layers are:

- API schemas and routes: transport validation and status mapping.
- Authentication service: normalization, Argon2 hashing/verification, session lifecycle.
- Persistence models/repositories: users and sessions with foreign keys and indexes.
- `current_user` dependency: reusable authenticated-user boundary for later project routes.
- Project access placeholder: extension point for membership authorization in the next slice.

Logout revokes the database session and expires the cookie. Expired, revoked, or disabled-user sessions are rejected. No session identifier, password, hash, or token is returned in JSON responses.
