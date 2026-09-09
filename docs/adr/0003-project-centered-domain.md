# ADR-0003: Project-Centered Domain

Status: Accepted

## Context

Prompt quality depends on conversations, documents, requirements, context, model runs, and versions. Treating a prompt as the root would lose that relationship.

## Decision

Make `Project` the central aggregate and model prompts as versioned project artifacts.

## Consequences

Authorization, persistence, navigation, and audit flows are project-scoped. Prompt APIs must carry project context and provenance.
