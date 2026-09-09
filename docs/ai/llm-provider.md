# LLM Provider

`LLMProvider` is a replaceable protocol. Configuration uses `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`; secrets are not stored in analysis records. The application runs without a provider in baseline fallback mode. Local OpenAI-compatible servers are the future integration target.
