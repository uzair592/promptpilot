# Adaptive Re-analysis Loop

Answers are retained as authoritative user facts and gaps are not automatically marked fully resolved. Re-analysis uses a typed `AnalysisInput` containing the immutable original prompt, task category, active memory, and relevant answers. The answer API returns the new analysis, active memory, session state, and next question so the UI can update without a refresh.
