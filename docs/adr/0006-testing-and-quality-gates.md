# ADR-0006: Testing and Quality Gates

Status: Accepted

## Context

The platform combines frontend, API, domain, persistence, file processing, and probabilistic AI behavior. Manual testing alone will not provide reliable evidence.

## Decision

Require formatting, linting, type checking, unit tests, integration tests for API contracts, and targeted end-to-end tests. AI behavior is evaluated with versioned fixtures, mocks, metrics, and human review criteria.

## Consequences

Every vertical slice carries test evidence and evaluation metadata. Some provider-specific results remain non-deterministic and must be reported with suitable tolerances.
