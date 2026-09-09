# ADR-0011: Immutable Artifact Versions

Status: Accepted

## Context

Prompt improvement and response evaluation require comparing the exact context, requirements, prompt, model, and output used at a point in time.

## Decision

Draft records may be edited while unapproved. Published context packages, requirements, prompts, generated documents, model-run inputs/outputs, and evaluations are immutable snapshots linked to source versions. Corrections create new versions; `artifact_versions` records common metadata without replacing domain-specific tables.

## Consequences

Storage grows over time and retention must be designed. Auditability and reproducibility are stronger, and evaluations can always identify their source artifacts.
