# Context Assembly

URL ingestion is isolated behind HTTP/HTTPS validation, DNS/IP private-network
rejection, redirect revalidation, bounded response size, and connect/read timeouts.
HTML is parsed without executing JavaScript.

The assembler accepts a typed `ContextAssemblyInput` containing the project, task,
optional conversation/message/analysis identifiers, retrieval limit, budget, and
filters. It creates one deterministic candidate set from relevant active memory,
project-scoped user answers, explicit analysis constraints, and lexical document
chunks. Candidates are ranked by task-term overlap multiplied by source authority;
user memory receives a small authority bonus. Normalized duplicate text is merged
and provenance is retained in `also_supported_by` metadata.

Selection applies one character budget across all sources. Candidates that do not
fit are omitted with source, identifier, score, priority, and reason metadata. The
current requirements schema is not yet present, so requirements remain an empty
typed collection until the requirements domain is introduced; analysis gaps are
only promoted when explicitly classified as constraints.

`ContextAssembler` combines active Project Memory with top-ranked project document chunks. Memory is included first because user-provided structured facts are authoritative; chunks are included by lexical relevance until the character budget is reached. Omitted chunks are counted and selected sources retain provenance.
