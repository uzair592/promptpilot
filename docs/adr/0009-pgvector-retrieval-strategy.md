# ADR-0009: Delayed pgvector Introduction

Status: Accepted

## Context

Document retrieval is required, but vector dimensions, corpus size, chunking, and query behavior should be validated before choosing index parameters.

## Decision

Persist document chunks and provenance first. Add pgvector embeddings behind `EmbeddingProvider` when retrieval is implemented, with embedding model/dimension metadata and benchmark-driven indexes. PostgreSQL remains authoritative.

## Consequences

Early document work is testable without committing to a retrieval index. A later migration must handle embedding backfill, model changes, and mixed dimensions deliberately.
