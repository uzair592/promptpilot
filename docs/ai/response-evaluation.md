# Response Evaluation

## Inputs

Original intent, approved requirements, constraints, expected output, applicable format rules, generated response, and relevant context.

## Output

Return the weighted response scores, explanations, strengths, weaknesses, comparison winner, and evaluator metadata. The evaluator must score exactly relevance, completeness, instruction following, contextual grounding, and clarity.

The evaluator must distinguish failure to verify from failure to satisfy. It must never claim certainty for a requirement that cannot be checked from available evidence.

## Response comparison milestone

The API supports deterministic single-response evaluation and paired baseline versus
PromptPilot comparisons. Every result records exactly five dimensions:

| Dimension             | Weight |
| --------------------- | -----: |
| Relevance             |    25% |
| Completeness          |    20% |
| Instruction following |    20% |
| Contextual grounding  |    20% |
| Clarity               |    15% |

The weighted aggregate is calculated by the backend and cannot be supplied by a
client or an LLM judge. The default evaluator is deterministic and explainable;
the optional LLM judge uses strict structured output and neutral Response A/B
labels. Paired runs must share project, conversation, and source task and both
must have succeeded. Evaluator metadata retains the original task, executed
prompts, responses, requirements, constraints, and context. Results are
persisted for history and are available from the conversation workspace.

The heuristic evaluator is a deterministic baseline approximation, not a
human-level semantic or factual judge. It uses lexical coverage, explicit
requirement and constraint checks, simple supplied-context contradiction
patterns, and basic readability signals. Missing requirements or context are
not fabricated; the corresponding dimensions are reported as having no
additional evidence rather than inferred from response length.
