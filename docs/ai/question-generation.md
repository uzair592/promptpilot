# Question Generation

The first implementation uses each gap's validated `question_target` as a deterministic, provider-independent question. This is intentionally safe and avoids inventing questions. A future provider-backed generator can replace this boundary while retaining question-type validation.
