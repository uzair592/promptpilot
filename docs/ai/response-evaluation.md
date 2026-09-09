# Response Evaluation

## Inputs

Original intent, approved requirements, constraints, expected output, applicable format rules, generated response, and relevant context.

## Output

Return overall score, requirement-level status (`satisfied`, `missing`, `partial`, `uncertain`, or `not_applicable`), constraint compliance, completeness, relevance, consistency, format compliance, weak areas, explanation, recommendations, evaluator metadata, and confidence.

The evaluator must distinguish failure to verify from failure to satisfy. It must never claim certainty for a requirement that cannot be checked from available evidence.
