# Analysis Schema

`PromptAnalysis` stores the project, conversation, source message, category, normalized score, status, and analyzer version. Child `PromptAnalysisDimension` rows store applicability, score, status, evidence, and explanation. `InformationGap` rows store dimension, severity (`critical`, `important`, or `optional`), description, and a future question target. This typed relational model is the contract for the future Dynamic Question Engine.
