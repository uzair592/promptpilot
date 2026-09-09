# Security Architecture

## Boundaries

- Authentication terminates at the API boundary; sessions/tokens are validated before use cases.
- Project authorization is enforced in application services and repository queries, not only in UI visibility.
- File authorization checks project membership before metadata, signed download, or processing access.
- Provider secrets exist only in environment/configuration and provider adapters; they never enter database rows, browser payloads, logs, or prompts.
- System prompts and policy instructions are server-side assets and are never returned as ordinary artifacts.
- User messages, document text, retrieved references, external URLs, and model output are untrusted content and are delimited from system instructions.
- External URL retrieval, when introduced, requires allowlisting, timeout, size limits, content validation, and provenance.
- Generated code never executes directly on the main application host. Any future execution requires an isolated sandbox with resource limits and a separate ADR.

## Controls

Validate schemas, MIME/type signatures, size, filenames, and content states. Apply rate limits to expensive AI and upload operations. Redact secrets and sensitive content from logs. Encrypt transport and managed storage in deployment. Record authorization failures and AI operations without recording secret prompt material.

## Threats

Key threats are cross-project data access, malicious files, prompt injection, provider leakage, oversized/complex documents, replayed operations, and over-trusted AI output. The design responds with authorization, bounded parsing, trust labels, immutable provenance, idempotency, and human approval for consequential artifacts.
