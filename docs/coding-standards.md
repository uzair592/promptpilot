# Coding Standards

## General

- Prefer small modules with one clear responsibility.
- Keep framework, vendor, and transport code at the edges.
- Use explicit names and typed boundaries; avoid `any` and unvalidated dictionaries at public interfaces.
- Keep functions deterministic where possible and inject time, IDs, storage, and AI providers when behavior depends on them.
- Document decisions and security assumptions, not obvious syntax.

## TypeScript

- Use strict TypeScript and immutable data by default.
- Keep React components focused on rendering and interaction wiring.
- Put business rules in domain/application modules, never directly in UI components.
- Use ESLint and Prettier through the root scripts.
- Validate external data before converting it to domain types.

## Python

- Use Python 3.12+, type annotations, small async-aware services, and explicit dependency injection.
- Use Ruff for formatting/lint rules and mypy in strict mode.
- Keep FastAPI route handlers thin; call application services.
- Raise domain-specific errors and map them to HTTP responses at the API boundary.

## Data and Security

- Use migrations for schema changes; do not mutate production schemas manually.
- Use UTC timestamps and UUIDs consistently.
- Treat filenames, MIME types, document text, prompts, and model output as untrusted input.
- Never commit secrets, personal data fixtures, or raw uploaded documents.
- Add audit metadata for security-sensitive and AI operations.

## Testing and Review

- Name tests after observable behavior.
- Test failure paths, authorization, validation, and provider failures.
- Every behavior change includes focused tests and updates documentation when a contract changes.
- Run formatting, linting, type checks, and tests before review.
