# ADR-0004: AI Provider Abstraction

Status: Accepted

## Context

The FYP should primarily use open-source or open-weight models while retaining the ability to compare or replace providers.

## Decision

Define ports for LLM, embeddings, retrieval, analysis, question generation, requirement extraction, prompt generation, response evaluation, and model routing. Implement adapters outside the domain layer.

## Consequences

Provider-specific capability differences must be normalized and recorded. Fake providers can make tests deterministic; production configuration selects an adapter without changing use cases.
