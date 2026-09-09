# ADR-0005: Security and File Processing

Status: Accepted

## Context

Uploaded documents and model-generated text are untrusted. Future project execution could create high-impact risks.

## Decision

Validate file type and size, process documents through controlled parsers, separate user content from system instructions, protect secrets and system prompts, record AI operations, and prohibit host execution of uploaded or generated code. Future execution requires an isolated sandbox.

## Consequences

Ingestion has explicit limits and failure states. Some automation ideas are deferred until an isolation design, threat model, and resource policy exist.
