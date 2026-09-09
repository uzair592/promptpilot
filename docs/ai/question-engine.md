# Dynamic Question Engine

The engine consumes unresolved `InformationGap` rows from an analysis and creates one prioritized question at a time. Critical gaps rank above important and optional gaps. User answers are authoritative, resolve the associated gap, and are retained as auditable `Answer` rows. Skipped questions are not repeated in the same session. No documents, embeddings, RAG, or Context Engine are used in this slice.
