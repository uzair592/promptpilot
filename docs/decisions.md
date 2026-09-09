# Architecture Decisions

The detailed records are in `docs/adr/`. The current decisions are:

- ADR-0001: Use a TypeScript/Python modular monorepo.
- ADR-0002: Keep framework and vendor code behind application/domain boundaries.
- ADR-0003: Make `Project` the central domain aggregate.
- ADR-0004: Use replaceable AI provider ports and adapters.
- ADR-0005: Treat documents and generated content as untrusted; isolate future execution.
- ADR-0006: Make automated quality gates and measurable evaluation first-class.
- ADR-0007: Complete product specification before feature implementation.
- ADR-0008: Use PostgreSQL as the source of truth.
- ADR-0009: Introduce pgvector after retrieval benchmarks.
- ADR-0010: Use versioned REST contracts for the frontend boundary.
- ADR-0011: Make published artifact versions immutable.
- ADR-0012: Hide file storage behind a local-first abstraction.
