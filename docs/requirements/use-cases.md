# Use Cases

| ID     | Actor      | Goal                        | Main result                                                   |
| ------ | ---------- | --------------------------- | ------------------------------------------------------------- |
| UC-001 | User       | Create a project            | Authorized project exists                                     |
| UC-002 | User       | Submit a task               | Initial intent and analysis are recorded                      |
| UC-003 | User       | Clarify missing information | Context completeness increases or question value becomes low  |
| UC-004 | User       | Add reference material      | Validated, provenance-linked context is available             |
| UC-005 | User       | Review requirements         | Requirements are approved, edited, or marked uncertain        |
| UC-006 | User       | Generate a prompt           | Versioned structured instruction package exists               |
| UC-007 | User       | Choose a model              | User-selected or recommended model is recorded                |
| UC-008 | User       | Evaluate a response         | Coverage, gaps, uncertainty, and recommendations are recorded |
| UC-009 | User       | Generate project documents  | Approved-context-based documents are versioned                |
| UC-010 | Supervisor | Inspect evidence            | Project history and evaluation artifacts are auditable        |

Every use case must enforce authorization, preserve provenance, and define recoverable failure states.
