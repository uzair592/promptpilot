# Controlled production-pipeline benchmark adapter: design

Status: offline adapter and live-study protocol admission validator implemented; no live
experiment or live runner is implemented. The existing
`benchmark_infrastructure_smoke_test` and its deterministic
`default_prompt_builder` remain unchanged. This design describes a separate
experiment scope, `production_pipeline_paired_v1`, using the existing `v1`
evaluation rubric and backend-owned weighted aggregate.

The separate typed protocol contract and fail-closed offline admission report are
documented in [live-study-protocol-admission.md](live-study-protocol-admission.md).
Durable run accounting and atomic call reservation are documented in
[benchmark-provider-call-ledger.md](benchmark-provider-call-ledger.md); that layer still
does not execute or authorize live provider calls.
Protocol validation freezes study-owner choices, verifies fixture declarations through
the existing dataset-bound and live-manifest boundaries, and checks worst-case provider
budgets. It does not construct a provider or establish that human review, consent,
provenance, or approval actually occurred.

The service-reuse prerequisite is implemented separately: production routes now
use `question_service.create_question_session` and
`question_service.skip_and_next_question`, while retaining route-level project
authorization and the existing commit order. `analyze_hybrid` and
`question_service.next_question` accept optional injected providers and
`ProviderObserver` callbacks. Omitting both arguments preserves production
provider selection. An injected provider is called even with no configured
live credentials, enabling offline adapter tests without network access.

The observer receives a `ProviderCallObservation` with purpose, safe
provider/model labels, a SHA-256 of request material without headers or
credentials, call start/end times, latency, `request_outcome`, `service_result`,
and `fallback_reason`. `not_attempted` plus `not_configured` means no request;
`failed` plus `provider_failed` means an attempted request failed and the
service used deterministic fallback; `succeeded` plus `duplicate_question`
means a question request succeeded but its text duplicated a prior question.
Successful provider output rejected by question validation is recorded as
`succeeded` plus `invalid_question`. Observer failures are ignored by product
services. Provider construction is never counted as a request. Expected
`reanalyze_after_answer` remains heuristic and is not a provider failure.
These observations originate as in-memory callbacks. The offline-only
orchestrator persists them with its stage ledger;
see [offline-production-benchmark.md](offline-production-benchmark.md). The
offline fixture and policy are not an approved live protocol.

## Research target and unit of isolation

The unit is one dataset task in one repetition. Use the same fixed task selection
and two repetitions as the smoke pilot only after its input fixtures are
approved. Each unit gets a new project with active owner membership through
`project_service.create_project`, a new conversation through
`conversation_service.create_conversation`, and one original user message through
`conversation_service.add_message`. Do not reuse a project, memory row, question
session, document, or conversation across repetitions. Persist the task ID,
repetition, fixture-manifest hash, project/conversation/source-message IDs, and
repository revision before provider calls. Check owner access with
`project_policy.require_project_access`.

The baseline sends exactly that original message. It never receives the
analysis, answers, project memory, retrieved chunks, assembled context, or
generated prompt. The treatment receives only material admitted through the
production services below. Neither branch receives evaluation-only reference
information as generation input.

## Exact production service sequence

The offline adapter orchestrates these existing functions. Shared question
service functions now own session creation and skip persistence; direct SQL
inserts do not replace document, question-answer, memory, retrieval, prompt,
or execution services.

| Step | Call and data flow | Required record |
| --- | --- | --- |
| 1 | `project_service.create_project(db, owner, ProjectCreateRequest(...))`, `conversation_service.create_conversation(db, project, ConversationCreateRequest(...))`, then `conversation_service.add_message(db, conversation, MessageCreateRequest(role="user", content=task.task_text), idempotency_key)` | Owner membership and source message IDs; one distinct project/conversation per repetition. |
| 2 | For separately approved, fixed user-provided project facts, call `ProjectMemoryService.add_user_answer(db, project.id, subject, content)`. For frozen document bytes, call `DocumentService.ingest_file(db, project.id, name, media_type, content, provenance=...)`; inspect `Document.status`, checksum, `DocumentChunk` IDs and provenance. Do not use `UrlIngestionService.fetch` for a controlled frozen fixture. | Fixture ID, exact bytes/hash, user/document origin, resulting memory/document/chunk IDs and processing status. |
| 3 | Call `analyzer_v2.analyze_hybrid(db, project.id, conversation.id, message, mode="hybrid")`. As `analysis_routes.create_analysis` does, create a `QuestionSession(project_id=..., conversation_id=..., analysis_id=analysis.id)` and commit. | Analysis ID, dimensions/gaps, `analysis_mode`, `ai_succeeded`, `fallback_used`, provider/model, and call outcome. |
| 4 | Call `question_service.next_question(db, session)` until it returns `None` or a preregistered cap is reached. For a fixture-matched presented question, call `question_service.answer_question(db, question, answer_text)`, `ProjectMemoryService.add_user_answer(db, project.id, question.text, answer.content)`, then `question_service.reanalyze_after_answer(db, session, answer)`, matching the order in `question_routes.submit_answer`. For a preregistered skip, use the existing `question_routes.skip_question` behavior (set the presented question to `skipped`, commit, then call `next_question`); the small implementation should extract this into a reusable service function shared by the route and adapter. | Every question ID, gap ID, source (`ai`/`fallback`), answer ID and fixture key or skip reason, reanalysis ID, session stop reason, and attempted provider call. |
| 5 | Call `prompt_generation.build_generation_input(db, message, latest_analysis, fixed_mode, instruction="")`. It invokes `ContextAssembler.assemble` with project, conversation, task and analysis IDs; that invokes `LexicalContextRetriever.retrieve` and `ProjectMemoryService.active`. Use the returned `PromptGenerationInput` and `ContextPackage` directly. | All selected source IDs/provenance/scores, document and answer IDs, omitted items and reasons, budget, generation mode, and the exact generation input. |
| 6 | Call `PromptGenerator(provider).generate(input_data)`, then `prompt_generation.persist_generation(db, message, latest_analysis, outcome, message.content, fixed_mode, package)`. Validate `incorporated_context` against `allowed_source_ids`, as the service already does. | Provider/model, call status, `GenerationOutcome.fallback_used`, prompt-version ID, source-message/analysis lineage, generated prompt, assumptions/warnings, incorporated source IDs. |
| 7 | Only for a treatment eligible for paired execution, call `LLMExecutionService.execute(db, None, message, None, same_parameters, "baseline")` and `LLMExecutionService.execute(db, version, message, None, same_parameters, "promptpilot")` in the documented alternating order: baseline first in repetition 1, PromptPilot first in repetition 2. | Both `ModelRun` IDs, actual executed prompts, raw responses, provider/model, parameters, usage, latency, status/errors, timestamps, and execution order. |
| 8 | Call `ResponseEvaluationService.evaluate_pair(db, conversation.id, baseline.id, promptpilot.id, task.task_text, fixed_method, original_task=task.task_text, requirements=..., constraints=..., context=...)` only after `validate_pair` accepts two succeeded runs. | `Evaluation`/item IDs, method, evaluator provider/model, neutral A/B assignment when judging, exact `v1` dimensions and scores, weighted scores, and failures. |

The unchanged `v1` rubric is relevance 25%, completeness 20%, instruction
following 20%, contextual grounding 20%, and clarity 15%. The backend computes
`round(sum(score * weight) / 100, 2)`; the adapter never recomputes or replaces
the aggregate.

No adapter-specific prompt builder may substitute for steps 3–6. In particular,
the existing smoke runner's `default_prompt_builder` is not part of this path.
The `PromptGenerator` has no deterministic fallback: provider or validation
failure stops treatment generation. Its `fallback_used=False` field alone is
not proof that earlier analysis or questions used AI successfully.

## Fixture admission and provenance

Create a separate, reviewed fixture manifest keyed by stable task ID and
version/hash. It must distinguish `original_task`, `user_supplied_answer`,
`user_supplied_project_fact`, `frozen_document`, and `evaluation_only` fields.
The manifest may contain a fixed answer only when a human has supplied or
approved that exact answer for the task. Match it to a generated gap by a
stable, reviewed semantic key such as dimension plus normalized
`question_target`; record the runtime gap/question UUID and reject ambiguous
or unmatched mappings. Never derive an answer from the evaluator's reference,
expected output characteristics, or model output. The question text itself is
not a stable key because provider wording may vary.

`ProjectMemoryService.add_user_answer` stores `source="user"` and
`category="user_answer"`; use it only for approved user facts. Do not convert
generic `available_context` annotations into user memory by assumption. Frozen
file fixtures go through `DocumentService.ingest_file`, which computes the
checksum and creates provenance-bearing chunks. Record the source fixture ID
alongside the resulting document/chunk IDs; do not fetch mutable public URLs
mid-run. A `source_type="url"` snapshot is acceptable only with its original
URL, frozen bytes, and checksum clearly distinguished from a live URL fetch.

The current dataset supplies task text, broad `available_context` annotations,
requirements, constraints, and expected output characteristics, but no fixed
clarification answers, approved memory facts, frozen document bytes, stable
gap-to-answer mappings, or human labels. All `reference` fields are null.
The summary policy and invoice text are already inside their original task
messages; duplicating them as treatment-only documents would change the
comparison. Other context annotations also lack proof of user/document origin.
Until fixtures are reviewed, those annotations stay evaluation metadata and
cannot silently enter the treatment. A synthetic fixture can exercise every
production stage in offline tests without changing benchmark tasks.

## Completion, fallback, and failure rules

Keep a stage ledger with `not_started`, `attempted`, `succeeded`, `fallback`,
`skipped`, and `failed` outcomes. A **complete production-pipeline pair** needs
approved fixture inputs, processed required documents, a successful AI
analysis if AI analysis is preregistered, resolved required questions with
fixture-backed answers, successful production prompt generation, two succeeded
same-model target runs, and a successful `v1` paired evaluation. The ledger,
not a non-null `PromptVersion` or score, decides this status.

`analyze_hybrid(mode="hybrid")` can return a heuristic result after provider
failure; its `ai_succeeded=False` / `fallback_used=True` is a partial-pipeline
outcome, never full AI-analysis success. `question_service.next_question`
silently catches provider errors and may use deterministic text; `Question.source`
marks `fallback`, but a provider-call ledger is needed to distinguish missing
configuration, attempted failure, and duplicate-question fallback. Record
every skip, absent fixture answer, unresolved gap, cap reached, and session
`stop_reason`; none is converted into a fabricated answer. Preregister whether
such units are excluded from the strict complete-pair analysis or reported as
a separate partial-pipeline stratum. Do not silently drop them.

`reanalyze_after_answer` calls `analyzer_service.analyze_input`, a heuristic
reanalysis; it does not repeat AI reconciliation. Export the initial and latest
analysis IDs and their modes separately so an initial successful AI call does
not make the later heuristic analysis look AI-generated.

`DocumentService.ingest_file` can return `status="failed"`; reject the
treatment if a required fixture fails. `PromptGenerator.generate` may raise
`ProviderUnavailable` or `ValueError`; retain the stage failure and do not
manufacture a prompt. `LLMExecutionService.execute` persists failed
`ModelRun`s; retain them without evaluation. If treatment preparation fails,
record the failure and make no target pair claim. For successful preparation,
preserve the alternating target order. Judge failure leaves the raw target
runs visible but no complete evaluated pair. Never relabel deterministic
fallback, missing configuration, or a baseline-only run as live full-pipeline
evidence.

## What the comparison can answer

The main paired comparison tests the **whole context-acquisition and prompt
generation workflow** against the original-task baseline. The treatment may
receive genuine extra user answers, memory, or documents. A score difference
therefore combines information acquisition, context selection, and prompt
wording; it does not identify a prompt-wording effect alone. Both responses
must be judged against the same frozen evaluation criteria, which remain
separate from generation inputs. An isolated wording study would need a
different, preregistered arm in which both target requests receive identical
context while only wording varies. That arm is outside the smallest adapter
milestone. No superiority claim follows from this design.

## Export and provider-call contract

Keep the smoke-test export schema/behavior intact and write a distinct
`experiment_scope="production_pipeline_paired_v1"` record. Export the full
fixture manifest ID/hash and admission decisions; task/repetition and
project/conversation/message IDs; all analysis, session, gap, question,
answer, memory, document, chunk, context-source, prompt-version, model-run,
and evaluation IDs; each stage input/output hash, status and sanitized error;
selected and omitted context with provenance, scores and budget; generation
mode, assumptions, incorporated IDs and fallback flags; raw target prompts,
responses, usage and parameters; target order; `v1` evaluation items, A/B
assignment and aggregate; dataset/repository revisions and timestamps. Keep
failed and partial units in both JSON and CSV. Exports and logs must redact
the configured credential and never contain authorization headers.

Log provider calls by purpose (`analysis`, `question`, `prompt_generation`,
`target_baseline`, `target_promptpilot`, `judge`) with provider/model,
sanitized request hash, parameters, start/end time, latency, attempt and
outcome. `analyze_hybrid` and `next_question` currently instantiate providers
internally, and question errors can be swallowed; the smallest implementation
should add optional provider injection or a narrow call-observer hook to those
services while retaining their default product behavior. The adapter can
already inject the provider into `PromptGenerator`, `LLMExecutionService`, and
`ResponseEvaluationService`. Count failed calls as attempts, not successes.

For 16 fully prepared pairs, expect 32 target calls, up to 16 initial AI
analysis calls, 16 prompt-generation calls, and one question-generation call
per presented question. Thus successful pairs require **64 + Σqᵢ** provider
calls with heuristic evaluation, where `qᵢ` is the attempted question count
for pair `i`; `llm_judge` adds 16 calls. Relative to the 32-call smoke pilot,
the added budget is **32 + Σqᵢ** (or **48 + Σqᵢ** with judging). Reanalysis,
memory, document ingestion from frozen bytes, lexical retrieval, and context
assembly make no provider calls today. A preregistered question cap gives the
actual upper bound; failures may make fewer downstream calls.

## Smallest implementation milestone and offline acceptance

The first item below now has a standalone fixture contract, offline validator,
and synthetic test fixture; see
[production-benchmark-fixtures.md](production-benchmark-fixtures.md). This does
not execute the production pipeline or admit the synthetic fixture to a live study.

1. Add a separate fixture manifest and validator with explicit source type,
   task ID, reviewed answer/gap key, document bytes/checksum, and
   evaluation-only boundary. Do not change task text to improve scores.
2. Add a separate orchestrator that calls the services above; share only the
   existing paired execution/evaluation/export primitives that preserve the
   smoke runner's behavior. Extract question-session creation and skip logic
   from their current routes into shared service functions, and add minimal
   provider injection or observation for analysis and question generation.
   Do not introduce agents, embeddings, or a database redesign.
3. Add the stage ledger and distinct scope to JSON/CSV exports, with a strict
   complete-pair flag and explicit partial/failure categories.
4. With fake providers and a synthetic, reviewed test fixture, assert actual
   calls to `analyze_hybrid`, `next_question`, `answer_question`,
   `ProjectMemoryService.add_user_answer`, `DocumentService.ingest_file`,
   `ContextAssembler.assemble` (through `build_generation_input`),
   `PromptGenerator.generate`, `persist_generation`,
   `LLMExecutionService.execute`, and `ResponseEvaluationService.evaluate_pair`.
   Verify owner access, isolation across repetitions, context source IDs and
   omissions, no evaluation-only leakage, exact baseline task, same target
   provider/model/parameters, alternating order, neutral A/B mapping, and the
   unchanged five-dimension `v1` aggregate.
5. Cover absent answers, skipped questions, duplicate or fallback questions,
   analysis/provider failure, document processing failure, generation failure,
   target failure, judge failure, no configured provider, and export redaction.
   Assert none becomes a complete full-pipeline pair; assert raw partial
   artifacts and call attempts remain inspectable. Run the unchanged smoke
   tests as a regression gate. No live calls are needed for acceptance.

## Research decisions before a live study

The protocol schema now requires these decisions to be explicit before it reports
technical readiness. The checked-in synthetic protocol intentionally fails live
admission, and no repository artifact supplies external human verification.

- Which dataset context facts can a human attest as user-provided, and which
  frozen documents and exact clarification answers may be admitted? Current
  fixtures do not support a document or answered-question production run.
- What stable gap keys and policy handle AI-generated gaps that differ from
  the reviewed answer manifest? What question cap and stop rule are fixed in
  advance?
- Is the primary estimand strict AI-backed end-to-end completion, or the
  product's hybrid behavior including clearly labelled fallbacks? Report both
  strata if both are studied; never merge them silently.
- Should the primary evaluation use heuristic scores, blinded LLM judging,
  human labels, or a preregistered combination? The exact `v1` rubric remains
  fixed in every case.
- Will analysis, question generation, prompt generation and target execution
  share the configured `LLM_MODEL`, as the current provider adapter does, or
  will a later protocol fix separate models and budgets for each role?
