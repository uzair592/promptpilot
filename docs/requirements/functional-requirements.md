# Functional Requirements

## ID Convention

IDs use `FR-<AREA>-<NUMBER>`. Areas are `AUTH`, `PROJ`, `CHAT`, `PA`, `QE`, `DOC`, `CTX`, `REQ`, `PG`, `MR`, `EVAL`, and `PLAN`.

## Requirements

- `FR-AUTH-001`: The system shall authenticate users and establish an auditable session.
- `FR-AUTH-002`: The system shall authorize every project operation by project ownership or explicit membership.
- `FR-PROJ-001`: A user shall create, view, update, archive, and list projects they are authorized to access.
- `FR-PROJ-002`: A project shall contain versioned conversations, context, requirements, prompts, model runs, evaluations, tasks, and generated documents.
- `FR-CHAT-001`: A user shall submit an initial natural-language task description in a project conversation.
- `FR-CHAT-002`: The system shall preserve messages with author, timestamp, role, and project provenance.
- `FR-PA-001`: The analyzer shall classify a request into an initial supported domain category.
- `FR-PA-002`: The analyzer shall assess intent, objective, audience, output, context, constraints, requirements, success criteria, dependencies, references, ambiguity, and missing critical information as applicable.
- `FR-PA-003`: The analyzer shall return score, status, dimension scores, explanation, gaps, and gap priority.
- `FR-QE-001`: The system shall generate questions from identified material information gaps rather than apply one fixed questionnaire.
- `FR-QE-002`: The question engine shall prioritize questions by expected impact, ask a small number at a time, avoid repetition, and allow skipping.
- `FR-QE-003`: The system shall recalculate completeness after accepted answers.
- `FR-DOC-001`: The system shall validate upload type, size, metadata, and authorization before processing.
- `FR-DOC-002`: The system shall safely parse supported PDF, DOCX, TXT, CSV, XLSX, and practical image inputs, with explicit failure states.
- `FR-DOC-003`: Extracted content shall retain source, page/sheet/section where available, chunk identity, and processing status.
- `FR-CTX-001`: The context engine shall combine intent, answers, requirements, constraints, documents, references, and classification into a bounded context package.
- `FR-CTX-002`: Context items shall distinguish user facts, cited sources, and AI inferences and shall not silently invent facts.
- `FR-REQ-001`: The system shall extract identifiable functional and non-functional requirements, roles, dependencies, constraints, and acceptance criteria where applicable.
- `FR-REQ-002`: Requirements shall have stable identifiers, source provenance, status, and uncertainty.
- `FR-PG-001`: The generator shall create versioned structured prompt artifacts containing role/instructions, objective, context, requirements, constraints, output format, success criteria, and validation instructions.
- `FR-MR-001`: The system shall rank available models using task category, reasoning, coding, multimodal, context, latency, cost, availability, and measured performance metadata.
- `FR-MR-002`: The user shall retain final model-selection control.
- `FR-EVAL-001`: The evaluator shall compare a supplied response with intent, requirements, constraints, expected output, and format.
- `FR-EVAL-002`: The evaluator shall report overall score, per-requirement status, missing requirements, weak areas, explanation, recommendations, and uncertainty.
- `FR-PLAN-001`: The system shall generate approved-context-based software planning artifacts including summary, requirements, SRS content, architecture, database requirements, tasks, phases, and testing plan.
- `FR-PROJ-003`: Important context, requirements, prompts, documents, model runs, evaluations, and generated documents shall be versioned and auditable.
