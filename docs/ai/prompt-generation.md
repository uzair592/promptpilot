# Prompt Generation

Prompt generation is a provider-independent service after analysis, clarification,
memory retrieval, and Context Assembly. `PromptGenerationInput` is typed and carries
the original message, analysis findings, selected answers, memory, constraints, and
the assembled package. The service sends this structured data to the configured
`LLMProvider`; it does not retrieve project records inside the model prompt.

The provider must return validated structured JSON. The backend owns provider/model,
mode, timestamp, fallback, and version metadata. `incorporated_context` is checked
against the deterministic package source identifiers, so fabricated provenance is
rejected. Supported modes are `structured`, `minimal`, and `detailed`.

Each generation is stored in `prompt_versions` with the original prompt, optimized
prompt, analysis reference, mode, provider/model, and version number. Regeneration
creates another version and does not overwrite history. Provider failures are
reported as unavailable; the system does not label an ungenerated prompt as AI
output.
