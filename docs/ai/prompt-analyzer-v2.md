# Hybrid Prompt Analyzer v2

V2 separates the deterministic baseline, an optional `LLMProvider`, and reconciliation. The baseline always runs first. AI output is validated with Pydantic before it can influence an analysis; unavailable or invalid providers fall back safely. The selected model is an implementation parameter and may be changed based on evaluation results, available hardware, latency, and quality.
