# ADR-0002: Modular Boundaries

Status: Accepted

## Context

AI features can become tightly coupled to HTTP routes, UI state, or one vendor unless the architecture establishes boundaries before feature work begins.

## Decision

Use API, application, domain, AI orchestration, document processing, persistence, storage, evaluation, and authentication boundaries. Dependencies point inward toward stable business concepts and interfaces.

## Consequences

There is some upfront structure and adapter code, but features can be tested without a live model or database and can evolve without rewriting the UI or route layer.
