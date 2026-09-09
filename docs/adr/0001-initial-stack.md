# ADR-0001: Initial Technology Stack

Status: Accepted

## Context

The FYP needs a familiar web interface, a productive API layer, relational persistence, vector retrieval, replaceable AI integrations, and testable development workflows.

## Decision

Use Next.js and TypeScript for the frontend, Python and FastAPI for the backend, PostgreSQL with pgvector for persistence, local file storage behind an abstraction, and pnpm plus Python tooling for development quality gates.

## Consequences

The repository has two language ecosystems and therefore two toolchains. The separation matches the strengths of each layer and keeps AI/domain logic independent from browser concerns. Shared transport contracts must be managed deliberately.
