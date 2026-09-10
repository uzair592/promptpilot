# PromptPilot Research Paths

The baseline experiment sends the original user prompt directly to a target LLM:

`Original Prompt -> Target LLM`

The PromptPilot path makes the context-engineering stages observable:

`Original Prompt -> Analysis -> Questions -> Answers -> Memory -> Retrieval -> Context Assembly -> Prompt Generation -> Prompt Version -> Target LLM`

The current FYP implementation uses deterministic lexical retrieval and mocked
providers in CI. It stores the source message, analysis reference, provider/model,
mode, selected context identifiers, and timestamp needed for a later comparison.
Response evaluation and objective comparison are intentionally future work.
