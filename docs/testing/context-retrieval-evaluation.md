# Context Retrieval Evaluation

Evaluation should verify project isolation, deterministic ordering, source-aware
ranking, normalized duplicate merging, relevant memory/answer selection, and
single-budget omission metadata. The mandatory fixture is the restaurant task:
menu requirements and menu chunks should be selected while historical sales and
old internal notes should not be selected solely because they share a project.

The deterministic baseline will be evaluated against future embedding and hybrid retrievers using precision@k, recall@k, human relevance judgments, context utilization, character efficiency, latency, and downstream answer quality. Current retrieval is lexical, project-scoped, deterministic, and provenance-preserving; no results are claimed yet.
