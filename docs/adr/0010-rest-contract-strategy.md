# ADR-0010: Versioned REST Contracts

Status: Accepted

## Context

The Next.js frontend and FastAPI backend need a stable boundary while domain and provider implementations evolve independently.

## Decision

Expose user-facing workflows through versioned REST endpoints under `/api/v1`, with typed request/response DTOs, consistent errors, cursor pagination, idempotency for expensive commands, and generated OpenAPI as a review artifact.

## Consequences

Transport contracts are public within the application and require compatibility discipline. The frontend cannot depend on ORM fields or provider-specific response shapes.
