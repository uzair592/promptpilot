# Question Generation

The engine sends a bounded `QuestionGenerationInput` containing the original prompt, task category, selected gap, active memory, and relevant prior questions/answers to the provider-neutral generator. Valid AI output is schema-checked; unavailable or invalid providers use the deterministic `question_target` fallback.
