# Entity Relationship Diagram

```mermaid
erDiagram
  USER ||--o{ PROJECT : owns
  USER ||--o{ PROJECT_MEMBER : joins
  PROJECT ||--o{ PROJECT_MEMBER : has
  PROJECT ||--o{ CONVERSATION : contains
  CONVERSATION ||--o{ MESSAGE : contains
  PROJECT ||--o{ PROMPT : owns
  PROMPT ||--o{ PROMPT_VERSION : versions
  PROJECT ||--o{ PROMPT_ANALYSIS : records
  PROMPT_ANALYSIS ||--o{ QUESTION : identifies
  QUESTION ||--o{ ANSWER : receives
  PROJECT ||--o{ DOCUMENT : stores
  DOCUMENT ||--o{ DOCUMENT_CHUNK : extracts
  PROJECT ||--o{ CONTEXT_ITEM : assembles
  PROJECT ||--o{ REQUIREMENT : defines
  REQUIREMENT ||--o{ REQUIREMENT_SOURCE : cites
  PROJECT ||--o{ MODEL_RUN : executes
  MODEL ||--o{ MODEL_RUN : serves
  PROMPT_VERSION ||--o{ MODEL_RUN : uses
  MODEL_RUN ||--o{ EVALUATION : produces
  EVALUATION ||--o{ EVALUATION_ITEM : contains
  REQUIREMENT ||--o{ EVALUATION_ITEM : assesses
  PROJECT ||--o{ TASK : plans
  PROJECT ||--o{ GENERATED_DOCUMENT : generates
  PROJECT ||--o{ ARTIFACT_VERSION : versions
  PROJECT ||--o{ AUDIT_EVENT : audits

  USER { uuid id PK }
  PROJECT { uuid id PK; uuid owner_id FK; string status }
  PROJECT_MEMBER { uuid project_id FK; uuid user_id FK; string role }
  CONVERSATION { uuid id PK; uuid project_id FK }
  MESSAGE { uuid id PK; uuid conversation_id FK; string role }
  PROMPT { uuid id PK; uuid project_id FK }
  PROMPT_VERSION { uuid id PK; uuid prompt_id FK; int version_no }
  PROMPT_ANALYSIS { uuid id PK; uuid project_id FK; string status }
  QUESTION { uuid id PK; uuid analysis_id FK; string status }
  ANSWER { uuid id PK; uuid question_id FK }
  DOCUMENT { uuid id PK; uuid project_id FK; string storage_key }
  DOCUMENT_CHUNK { uuid id PK; uuid document_id FK; int ordinal }
  CONTEXT_ITEM { uuid id PK; uuid project_id FK; string trust_class }
  REQUIREMENT { uuid id PK; uuid project_id FK; string stable_key }
  REQUIREMENT_SOURCE { uuid id PK; uuid requirement_id FK }
  MODEL { uuid id PK; string provider; string model_key }
  MODEL_RUN { uuid id PK; uuid project_id FK; uuid prompt_version_id FK; uuid model_id FK }
  EVALUATION { uuid id PK; uuid model_run_id FK }
  EVALUATION_ITEM { uuid id PK; uuid evaluation_id FK; uuid requirement_id FK }
  TASK { uuid id PK; uuid project_id FK }
  GENERATED_DOCUMENT { uuid id PK; uuid project_id FK }
  ARTIFACT_VERSION { uuid id PK; uuid project_id FK }
  AUDIT_EVENT { uuid id PK; uuid project_id FK }
```
