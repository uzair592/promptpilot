# Context Engine

## Context Package

```text
PROJECT CONTEXT
Objective
Task Type
User Intent
Requirements
Constraints
Facts
User Preferences
Relevant Sources
References
Expected Output
Success Criteria
Uncertainties and Open Questions
```

Each item includes provenance, trust class (`user_fact`, `source_content`, or `ai_inference`), confidence/uncertainty, relevance, and version. The engine preserves user facts, avoids silent invention, ranks relevant context, and enforces bounded size.

Untrusted document content is delimited as data. It cannot override system or application instructions. Context assembly is deterministic where possible and records inclusion/exclusion reasons for audit.
