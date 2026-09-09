# ADR-0012: Document Storage Abstraction

Status: Accepted

## Context

The FYP needs local development storage but should later support S3-compatible services without changing domain behavior. Large binaries should not be stored in PostgreSQL.

## Decision

Use a `FileStorage` port returning opaque storage references and metadata. Implement local filesystem storage first; add S3-compatible storage as an adapter later. Database rows store ownership, checksum, media metadata, and storage key only.

## Consequences

Upload, deletion, signed access, orphan cleanup, and database/object consistency become explicit application responsibilities. Local storage must never be treated as production security by default.
