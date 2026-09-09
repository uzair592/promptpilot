# Reconciliation

Hybrid analysis runs the baseline first, validates optional AI output, and preserves provider, model, and fallback metadata. Deterministic scoring and applicability remain authoritative; malformed or unavailable AI responses are discarded and the baseline is returned. This avoids blindly averaging model scores.
