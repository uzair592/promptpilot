# Prompt Analyzer

Prompt Analyzer v1 is a deterministic, provider-independent analysis service. It classifies a user message, scores task-aware dimensions, and records explainable information gaps. It does not use word count as the quality score and does not invent facts. Historical results are immutable records identified by `prompt-analyzer-v1`.

The current implementation is synchronous and intentionally leaves provider adapters, document context, and the Dynamic Question Engine for later slices.
