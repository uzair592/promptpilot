# AI Requirements

AI capabilities must be provider-independent, observable, bounded, and replaceable. Each AI operation receives a typed input, returns a typed result, validates output, records metadata, and has explicit timeout/failure behavior.

Required ports are `LLMProvider`, `EmbeddingProvider`, `DocumentParser`, `ContextRetriever`, `PromptAnalyzer`, `QuestionGenerator`, `RequirementExtractor`, `PromptGenerator`, `ResponseEvaluator`, and `ModelRouter`.

AI output is advisory unless the user explicitly approves an artifact. Provider output is untrusted and must not bypass authorization, validation, or system safety policy.
