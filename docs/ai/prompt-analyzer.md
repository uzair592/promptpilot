# Prompt Analyzer

## Inputs

Original request, relevant conversation state, project metadata, available context, and task/domain hints.

## Assessment

Assess intent clarity, objective, task type, audience, required output, context, constraints, requirements, format, success criteria, dependencies, references, ambiguity, and critical missing information. Dimensions are task-aware; irrelevant dimensions may be marked not applicable.

## Output

Return a numerical score, `Poor`/`Medium`/`Good` status, dimension scores, explanation, prioritized gaps, severity, confidence, analyzer version, and provenance references.

The score is an engineering heuristic and AI-assisted metric. It must be validated experimentally against human review and downstream response quality; it is not a truth claim and is not based on prompt length.
