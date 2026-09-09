# Sequence Diagrams

## Create Project

```mermaid
sequenceDiagram
  actor User
  participant UI as Frontend
  participant API
  participant App as Project Service
  participant DB as PostgreSQL
  User->>UI: Submit project metadata
  UI->>API: POST /projects
  API->>App: authorize and create
  App->>DB: insert project and audit event
  DB-->>App: project
  App-->>API: project response
  API-->>UI: 201 Created
```

## Submit and Analyze Prompt

```mermaid
sequenceDiagram
  actor User
  participant UI as Frontend
  participant API
  participant App as Conversation Service
  participant Analyzer as Prompt Analyzer
  participant DB as PostgreSQL
  User->>UI: Enter task description
  UI->>API: POST /projects/{id}/messages
  API->>App: authorize and persist message
  App->>Analyzer: analyze project input
  Analyzer-->>App: typed analysis and gaps
  App->>DB: persist message and analysis snapshot
  App-->>API: message plus analysis summary
  API-->>UI: 201 Created
```

## Generate Questions and Accept Answer

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API
  participant QE as Question Engine
  participant DB as PostgreSQL
  UI->>API: GET /projects/{id}/questions/next
  API->>QE: analysis, answered questions, policy
  QE-->>API: prioritized questions
  API-->>UI: question batch
  UI->>API: POST /questions/{questionId}/answers
  API->>DB: persist answer and context provenance
  API->>QE: recompute completeness
  QE-->>API: updated analysis status
  API-->>UI: answer and next-state
```

## Upload and Process Document

```mermaid
sequenceDiagram
  actor User
  participant UI as Frontend
  participant API
  participant Doc as Document Service
  participant Store as Object Storage
  participant Parser
  participant DB as PostgreSQL
  User->>UI: Select file
  UI->>API: POST /projects/{id}/documents
  API->>Doc: validate project, type, size
  Doc->>Store: write object
  Doc->>DB: create processing record
  Doc-->>API: document pending
  API-->>UI: 202 Accepted
  Doc->>Parser: parse controlled format
  Parser-->>Doc: normalized text and provenance
  Doc->>DB: chunks, status, errors
  Doc-->>UI: processing status available
```

## Assemble Context and Generate Prompt

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API
  participant Context as Context Service
  participant PG as Prompt Generator
  participant DB as PostgreSQL
  UI->>API: POST /projects/{id}/context-packages
  API->>Context: select relevant approved sources
  Context->>DB: read versioned facts and chunks
  Context-->>API: bounded context package
  UI->>API: POST /projects/{id}/prompts
  API->>PG: context, requirements, constraints
  PG-->>API: structured prompt artifact
  API->>DB: persist draft version
  API-->>UI: prompt version
```

## Recommend, Run, and Evaluate

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API
  participant Router as Model Router
  participant LLM as LLM Provider
  participant Eval as Evaluator
  participant DB as PostgreSQL
  UI->>API: GET /projects/{id}/model-recommendations
  API->>Router: task profile and model registry
  Router-->>API: ranked options with explanations
  API-->>UI: recommendations
  UI->>API: POST /projects/{id}/model-runs
  API->>LLM: normalized prompt and selected model
  LLM-->>API: response or provider error
  API->>DB: model run metadata and output reference
  UI->>API: POST /model-runs/{runId}/evaluations
  API->>Eval: intent, requirements, response
  Eval-->>API: overall and item findings
  API->>DB: evaluation snapshot
  API-->>UI: evaluation
```
