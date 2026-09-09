# Non-Functional Requirements

Targets marked TBE are to be established during implementation and evaluation rather than invented prematurely.

- `NFR-PERF-001`: Common project reads and navigation shall have a defined p95 latency target established during Phase 3 evaluation.
- `NFR-PERF-002`: Long-running AI and document jobs shall expose progress or a recoverable pending state and shall not block unrelated project actions.
- `NFR-REL-001`: A provider timeout or malformed output shall preserve prior valid artifacts and produce a retryable, auditable failure.
- `NFR-SEC-001`: Project data shall be isolated by authorization checks at API and application boundaries.
- `NFR-SEC-002`: Secrets shall come from configuration and never be stored in source or client-visible payloads.
- `NFR-SEC-003`: Uploaded content shall be treated as untrusted data; generated or uploaded code shall never execute on the application host.
- `NFR-MAINT-001`: Domain and application behavior shall be testable without a live LLM or vendor service.
- `NFR-MAINT-002`: Provider, parser, storage, and retrieval implementations shall be replaceable through interfaces.
- `NFR-OBS-001`: AI operations shall record provider, model, operation, timestamp, correlation identity, and normalized input/output metadata without protected system prompts.
- `NFR-USE-001`: Users shall understand score status, gaps, question purpose, processing state, uncertainty, and recovery action.
- `NFR-SCALE-001`: Storage, retrieval, and AI jobs shall have explicit boundaries that can later be moved to managed services or workers.
- `NFR-PORT-001`: Local development shall use documented environment templates and reproducible quality commands.
- `NFR-TEST-001`: Each major subsystem shall have unit tests and relevant integration or workflow evidence before release.
