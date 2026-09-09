# Evaluation Plan

## Research Questions

- Does analysis identify meaningful gaps better than a length-based baseline?
- Do adaptive questions improve context completeness without unnecessary burden?
- Does structured context improve prompt quality and response requirement coverage?
- Are evaluator findings consistent with human reviewers?
- Which model metadata factors predict useful recommendations?

## Fixtures

Create versioned examples across Software Development, Business Analysis, Data Analysis, Marketing, Education, Writing/Content, Research, and General Task. Each fixture contains an initial request, gold or reviewer-approved gaps, expected requirements, constraints, and evaluation notes.

## Measures

Measure gap precision/recall where labels exist, question relevance and answer burden, score correlation with human review, requirement extraction precision/recall, response coverage agreement, prompt improvement, latency, failure rate, and cost. Set numerical targets during implementation/evaluation when baselines are available.

## Test Layers

Unit tests cover domain policies and fake-provider behavior. Integration tests cover API contracts, authorization, persistence, file processing, and failure mapping. End-to-end tests cover the main journey. Evaluation runs are reproducible and record prompt, provider, model, fixture, version, and result metadata without secrets.
