# Hybrid Analysis Flow

The analyzer runs the deterministic baseline, optionally calls the configured provider, validates the typed response, and reconciles only validated findings. `baseline` never calls a provider; `ai` reports provider failure rather than silently claiming success; `hybrid` falls back to the baseline and records truthful provenance.
