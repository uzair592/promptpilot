# Acceptance Criteria

Acceptance criteria are written as observable statements and map to future automated tests.

- `AC-PA-001`: Given a request lacking critical task information, the analyzer identifies at least one meaningful gap.
- `AC-PA-002`: Given a simple task with sufficient information, the analyzer does not lower the score merely because the prompt is short.
- `AC-QE-001`: Given a material gap, the question engine produces a grounded, answerable, non-repetitive question.
- `AC-QE-002`: Given an answer, completeness is recalculated and the answer is linked to its source message.
- `AC-CTX-001`: Given approved answers and source documents, the context package contains provenance for each included fact.
- `AC-CTX-002`: Given untrusted document text containing instructions, the context engine treats it as content and does not override system instructions.
- `AC-DOC-001`: Given an unsupported or oversized file, processing is rejected with a useful recoverable reason and no partial trusted artifact.
- `AC-REQ-001`: Given a software task, extracted requirements include stable IDs and distinguish functional, non-functional, constraint, role, dependency, and acceptance concepts where present.
- `AC-PG-001`: Given approved context, the generated prompt contains objective, relevant context, requirements, constraints, output format, success criteria, and validation instructions.
- `AC-MR-001`: Given model metadata and a task profile, recommendations explain ranking factors and do not claim universal model superiority.
- `AC-EVAL-001`: Given requirements and a response, the evaluator reports satisfied, missing, and uncertain requirements separately.
- `AC-EVAL-002`: Given an unverifiable requirement, the evaluator marks uncertainty rather than pretending certainty.
- `AC-VER-001`: Given a changed prompt or context package, the previous artifact remains retrievable and linked to the new version.
- `AC-SEC-001`: Given a user without project access, project artifacts cannot be read or modified.
