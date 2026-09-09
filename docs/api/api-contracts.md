# Initial API Contracts

All paths use `/api/v1`; `{projectId}` must be authorized. Request and response examples are logical schemas; implementation may use a typed Python schema and generated OpenAPI without exposing persistence details.

Authentication endpoints return `{ "user": { "id", "email", "display_name", "status", "created_at", "last_login_at" } }` and set an HTTP-only session cookie. `POST /auth/logout` returns `204`. `GET /auth/me` requires the session cookie. Registration requires a valid email, non-blank display name, and password of at least 12 characters.

Conversation and message endpoints require project membership. Owners/editors may create and update conversations and append messages; members may read. Message creation stores the request only and never invokes an LLM or fabricates an assistant message. `Idempotency-Key` is optional and prevents duplicate retries within a conversation.

| Method/path                                       | Auth           | Request                                    | Response                    | Statuses                |
| ------------------------------------------------- | -------------- | ------------------------------------------ | --------------------------- | ----------------------- |
| `POST /projects`                                  | session        | name, description?, domain?                | project DTO                 | 201, 400, 401           |
| `GET /projects`                                   | session        | cursor, limit?                             | paged project DTOs          | 200, 401                |
| `GET /projects/{projectId}`                       | session/member | none                                       | project summary             | 200, 401, 403, 404      |
| `PATCH /projects/{projectId}`                     | owner/editor   | name, description?, domain?                | project DTO                 | 200, 400, 403, 404      |
| `POST /projects/{projectId}/archive`              | owner          | none                                       | archived project DTO        | 200, 403, 404, 409      |
| `POST /projects/{projectId}/conversations`        | editor/owner   | title                                      | conversation DTO            | 201, 400, 403, 404, 409 |
| `GET /projects/{projectId}/conversations`         | member         | cursor, limit?                             | paged conversation DTOs     | 200, 401, 404           |
| `GET /conversations/{conversationId}`             | member         | none                                       | conversation detail DTO     | 200, 401, 404           |
| `PATCH /conversations/{conversationId}`           | editor/owner   | title                                      | conversation DTO            | 200, 400, 403, 404, 409 |
| `POST /conversations/{conversationId}/messages`   | editor/owner   | role, content, Idempotency-Key?            | message DTO                 | 201, 400, 403, 404, 409 |
| `GET /conversations/{conversationId}/messages`    | member         | cursor, limit?                             | paged message DTOs          | 200, 401, 404           |
| `POST /projects/{projectId}/conversations`        | member         | title?                                     | conversation DTO            | 201, 400, 403           |
| `POST /projects/{projectId}/messages`             | member         | conversation_id, content                   | message + analysis state    | 201, 400, 403, 413      |
| `POST /projects/{projectId}/analyses`             | member         | source_message_id                          | analysis DTO                | 202/200, 400, 403, 502  |
| `GET /projects/{projectId}/questions/next`        | member         | max_count?                                 | prioritized question DTOs   | 200, 403                |
| `POST /questions/{questionId}/answers`            | member         | answer, action                             | answer + completeness state | 201, 400, 403, 404      |
| `POST /projects/{projectId}/documents`            | member         | multipart file, idempotency key            | document pending DTO        | 202, 400, 413, 415      |
| `GET /projects/{projectId}/documents`             | member         | cursor                                     | document DTOs               | 200, 403                |
| `POST /projects/{projectId}/context-packages`     | member         | source/version filters, token budget       | bounded package DTO         | 200, 400, 403, 409      |
| `GET /projects/{projectId}/requirements`          | member         | status?                                    | requirement DTOs            | 200, 403                |
| `POST /projects/{projectId}/prompts`              | editor         | context_version, requirement keys, options | prompt version DTO          | 201/202, 400, 403, 502  |
| `GET /projects/{projectId}/model-recommendations` | member         | prompt_version_id                          | ranked model DTOs           | 200, 403, 503           |
| `POST /projects/{projectId}/model-runs`           | editor         | prompt_version_id, model_id, input?        | pending run DTO             | 202, 400, 403, 503      |
| `POST /model-runs/{runId}/evaluations`            | member         | response, criteria?                        | evaluation DTO              | 201/202, 400, 403, 502  |
| `POST /projects/{projectId}/generated-documents`  | editor         | type, approved_versions                    | generated document DTO      | 202, 400, 403, 502      |
| `GET /projects/{projectId}/tasks`                 | member         | filters                                    | task DTOs                   | 200, 403                |

Validation includes max lengths, enum values, authorized project IDs, positive pagination limits, supported MIME/signature and upload size, approved version references, and non-empty response text. `401` means unauthenticated, `403` unauthorized, `404` not found or intentionally undisclosed, `409` version/state conflict, `413` too large, `415` unsupported media, `422` schema validation, `429` rate limit, `502/503` provider/service failure.

Project detail intentionally returns `404 Project not found` for both a missing project and an inaccessible project, preventing object enumeration. Archived projects remain readable to active members but reject update/archive mutations.
