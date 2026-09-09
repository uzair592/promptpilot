# User Journeys

## Main Journey

1. Sign in and create a project.
2. Enter a natural-language task description.
3. PromptPilot classifies the task and analyzes clarity, context, requirements, constraints, output, and success criteria.
4. PromptPilot reports a score, status, gaps, severity, and explanation.
5. The question engine asks a small prioritized set of relevant questions; the user may answer or skip.
6. Answers, conversation history, and optional uploads become versioned project context.
7. Documents are validated, parsed, normalized, chunked, and linked to provenance.
8. Requirements and constraints are extracted where the task permits it.
9. The context engine assembles a bounded, source-aware context package.
10. The prompt generator creates a structured instruction package and explains completeness.
11. The model recommender ranks available models using metadata and measured evidence; the user retains control.
12. The user copies, exports, or uses the prompt and may provide a generated response.
13. The evaluator reports requirement coverage, weak areas, uncertainty, and improvements.
14. The user revises or regenerates; artifacts remain versioned and auditable.

## Recovery Journey

Every external failure exposes a useful state, preserves the last valid artifact, offers retry where safe, and avoids silently losing answers, uploads, or versions.
