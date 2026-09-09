# Adaptive Re-analysis Loop

Answers are retained as authoritative user facts and gaps are not automatically marked fully resolved. The current implementation records partial resolution safely; the next refinement will feed the original prompt plus answers into a new historical PromptAnalysis and select the next question from that latest analysis.
