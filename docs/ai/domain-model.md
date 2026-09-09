# AI Domain Types

```text
TaskProfile { category, objective, audience, reasoning_level, multimodal_needed, confidence }
PromptAnalysis { score, status, dimensions, gaps, explanation, uncertainty, source_version }
Gap { key, dimension, description, priority, severity, expected_value, status }
Question { id, gap_key, text, rationale, priority, status, generated_by }
Answer { question_id, text, status, source_message_id, accepted_at }
ContextItem { kind, trust_class, content, source_ref, confidence, relevance, version }
Requirement { stable_key, type, statement, priority, status, certainty, acceptance_criteria, sources }
PromptArtifact { version, instructions, objective, context, requirements, constraints, output_format, success_criteria, validation }
ModelRun { prompt_version, provider, model, input_ref, output_ref, status, timestamps, usage_metadata }
Evaluation { overall_score, coverage, constraints, completeness, format, explanation, recommendations }
EvaluationItem { requirement_key, status, evidence, certainty, explanation }
```

The analyzer algorithm is behind `PromptAnalyzer.analyze(input) -> PromptAnalysis`; scoring weights and heuristics can evolve without changing callers. `LLMProvider.complete(request)`, `EmbeddingProvider.embed(texts)`, and `ModelRouter.recommend(profile, registry)` are normalized ports.
