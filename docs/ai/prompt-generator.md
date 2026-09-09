# Prompt Generator

The generator consumes approved task profile, intent, answers, requirements, context, constraints, expected output, and success criteria. It produces a versioned structured artifact with:

- role and instructions
- task objective
- context
- requirements
- constraints
- output format
- success criteria
- validation instructions

The generator records source versions and a safe generation summary. It must not invent user facts, expose protected system prompts, or discard material constraints without explanation.
