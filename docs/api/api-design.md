# API Design

The initial API is REST over HTTPS under `/api/v1`. Resources are project-scoped unless explicitly stated. Authentication uses the configured session/token boundary. Every request may carry `X-Request-Id`; the server returns a correlation ID.

## User-Facing Resource Groups

- Authentication: session, current user, sign out.
- Projects: create, list, read, update, archive, restore, members.
- Conversations/messages: create/list conversations, append messages, paginate history.
- Prompt analysis: analyze a project message and read analysis snapshots.
- Questions: get next questions, answer, skip, stop questioning.
- Documents: upload, list, inspect processing status, request authorized download.
- Context: preview/assemble bounded context package, approve/reject context items.
- Requirements: list, review/edit status, approve, trace sources.
- Prompt generation: create prompt version, list versions, publish/read prompt.
- Model recommendation: list ranked models with factor explanations.
- Model runs: start run, read status/output, retry safe failure.
- Evaluation: evaluate a model run, read evaluation and items.
- Generated documents: generate, list, read, export approved artifact.
- Tasks: create, update status, list project tasks.

Avoid one endpoint per database table. Endpoints represent user workflows and return stable DTOs, not ORM objects.

## Conventions

List responses use `{ "items": [], "page": { ... } }`. Success responses use the resource DTO or `{ "data": ... }` consistently within a route family. Errors use `{ "error": { "code": "...", "message": "...", "details": {}, "request_id": "..." } }`. Pagination is cursor-based for messages, chunks, and audit events. Idempotency keys are required for uploads and expensive generation/run commands.
