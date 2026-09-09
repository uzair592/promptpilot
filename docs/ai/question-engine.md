# Question Engine

The engine consumes an analysis and selects missing information that materially affects the outcome. It ranks gaps by expected value, risk, dependency, and user effort, then asks one or a small number of grounded questions.

Questions must be relevant, understandable, answerable, safe, non-repetitive, and tied to a gap. Users can answer, skip, edit, or stop. After an answer the engine updates context and recalculates completeness. It stops at a configured threshold, when marginal value is low, or when the user stops.

The engine must not pressure users to reveal unnecessary sensitive information or invent a gap merely to continue the conversation.
