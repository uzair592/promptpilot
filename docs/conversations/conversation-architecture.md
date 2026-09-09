# Conversation Architecture

A conversation is a project-scoped historical thread. Its project is the authorization boundary; conversation IDs are never authorized independently. Routes resolve `conversation -> project -> active membership` through the shared project policy.

The application service creates conversations and messages. Routes only validate transport input, request the authenticated user, call the service, and map domain/application failures to HTTP responses. No conversation operation calls an LLM in this slice.
