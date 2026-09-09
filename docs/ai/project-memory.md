# Project Memory

Project Memory is structured, project-scoped metadata rather than conversation history or retrieval infrastructure. User answers are stored as high-confidence `user_answer` items. Active values supersede prior values while preserving history. Memory is passed to analysis through `AnalysisInput`, and the original message remains unchanged.
