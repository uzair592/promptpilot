# Reconciliation

Hybrid analysis runs the baseline first, validates optional AI output, and preserves provider, model, and fallback metadata. Valid AI dimensions replace the corresponding baseline evidence and scores, AI gaps are merged and deduplicated, and the final score is recalculated deterministically from the resulting dimensions. Malformed or unavailable AI responses are discarded and the baseline is returned. This avoids blindly averaging model scores; the validated AI result is not discarded.
