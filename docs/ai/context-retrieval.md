# Context Retrieval

The FYP baseline is a deterministic lexical retriever. It scans processed chunks
belonging to the requested project, computes normalized token overlap plus an
exact-phrase bonus, then sorts by score and stable chunk UUID. This is an
application-side baseline and is intentionally not presented as scalable vector
retrieval; embeddings and pgvector are deferred.

Document chunks preserve order and provenance and are stored separately from Project Memory. Lexical retrieval and ContextAssembler are the next bounded increment; embeddings and vector search are intentionally not introduced here.
