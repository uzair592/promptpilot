# OpenRouter Provider

Set `LLM_PROVIDER=openrouter`, `LLM_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL`, `LLM_API_KEY`, and optional `LLM_TIMEOUT`. The key is backend-only and is never persisted or returned. The provider requests strict JSON schema output and validates the response with `AIAnalysis` before it can be used.

`openrouter/free` is suitable for development experimentation only because its underlying model can change. Use a fixed model identifier for reproducible evaluation.

OpenRouter requires an API key. A future trusted local OpenAI-compatible provider may allow a blank key, but that behavior is provider-specific and does not weaken OpenRouter validation.
