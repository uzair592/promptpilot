# Test Architecture

## Layers

- Domain unit tests: invariants, statuses, version immutability, score status mapping, trust/provenance rules.
- Application unit tests: use cases with fake repositories, storage, parsers, and providers.
- Adapter tests: FastAPI validation/error mapping, PostgreSQL repositories, storage implementation, and parser fixtures.
- API integration tests: authorized/unauthorized project access, contract schemas, pagination, idempotency, and failure states.
- Workflow end-to-end tests: create project through analysis, questions, context, prompt, model run, and evaluation using deterministic fake providers.
- Evaluation tests: versioned fixtures and human-reviewed expected findings; provider runs are separated from deterministic regression tests.

## Test Seams

Inject clock, UUID generator, repositories, object storage, parser, embedding provider, LLM provider, router, and evaluator. No test requires a real external provider. Database tests use an isolated PostgreSQL instance and migrations from scratch.

## Required Failure Coverage

Test malformed AI JSON, provider timeout, unavailable provider, oversized/unsupported/corrupt file, unauthorized project/document, archived project mutation, stale version, duplicate idempotency key, uncertain evaluation, and partial processing recovery.

## Evidence

CI should publish unit/integration results, coverage, migration status, type/lint results, and evaluation fixture summaries. Thresholds are established after the first vertical slice baseline.
