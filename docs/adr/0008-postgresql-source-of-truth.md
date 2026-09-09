# ADR-0008: PostgreSQL as Source of Truth

Status: Accepted

## Context

Projects combine relational ownership, versioned artifacts, audit records, and future vector retrieval. Splitting authority across providers would complicate consistency and evaluation.

## Decision

PostgreSQL is authoritative for identities, project metadata, relationships, artifact metadata, versions, AI operation records, and evaluation results. Object storage holds large binary content by reference.

## Consequences

Repositories and migrations are a first-class backend boundary. Binary retention and database/object-storage consistency require explicit cleanup and recovery workflows.
