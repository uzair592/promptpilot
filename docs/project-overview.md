# Project Overview

## Purpose

PromptPilot helps a user transform an incomplete or high-level task description into a structured, context-rich, validated AI instruction package. The FYP demonstrates conversational context engineering, prompt quality analysis, and measurable response evaluation.

## Product Scope

The initial product includes a ChatGPT-style workspace, project management, conversations, completeness scoring, dynamic follow-up questions, context collection, document ingestion, requirement extraction, prompt generation and optimization, model recommendation, response evaluation, domain-aware planning, and generated project documentation.

Autonomous coding, GitHub modification, deployment, domain purchase, hosting automation, and direct execution of generated code are explicitly out of scope for the FYP.

## Central Domain Entity

`Project` is the organizing aggregate. It owns or references conversations, messages, uploaded files, extracted documents, context, requirements, prompts, evaluations, model runs, generated documents, tasks, and versions. A prompt is an artifact within a project, not the application root.

## Quality Goals

- Clear modular boundaries and replaceable AI providers.
- PostgreSQL as the source of truth with migrations, constraints, and indexes.
- Secure file handling and prompt-injection-aware processing.
- Deterministic tests around domain behavior and provider ports.
- Auditable AI operations with model, provider, input, output metadata, and timestamps.
- A path to future multi-agent orchestration without implementing it now.

## Success Measures

The FYP should measure completeness-score usefulness, question relevance, requirement extraction accuracy, prompt quality improvement, response evaluation consistency, latency, cost, and failure behavior using reproducible fixtures and human review criteria.
