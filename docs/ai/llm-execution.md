# LLM Execution

PromptPilot supports two explicit execution paths without evaluation:

`Original Prompt -> Target LLM -> ModelRun` (baseline)

`Optimized Prompt -> Target LLM -> ModelRun` (promptpilot)

Both paths use the existing provider abstraction and persist provider/model,
response, finish reason, usage, latency, status, and the exact prompt sent. A
`ModelRun` references the source project, conversation, message, and optional
PromptVersion. Provider failures are persisted as failed runs and are never
reported as successful responses. Response evaluation is the next milestone.
