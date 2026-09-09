# OpenRouter Integration Tests

Provider tests should use a local mock HTTP server and deterministic structured responses. They must cover invalid JSON, schema failures, timeout, authentication, rate limits, and server failures without internet access or credentials. A real smoke test is optional and must never print or commit the key.
