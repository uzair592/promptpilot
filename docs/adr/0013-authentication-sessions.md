# ADR-0013: Argon2 and Opaque Database Sessions

Status: Accepted

## Context

The FYP needs browser authentication with logout invalidation, disabled-user protection, and a reusable current-user boundary. The frontend is same-origin in production but may be separately hosted during development.

## Decision

Hash passwords with Argon2 through `argon2-cffi`. Use random opaque session tokens in HTTP-only, SameSite cookies; store only a SHA-256 token hash, expiry, and revocation state in PostgreSQL. Use `Secure` cookies in production. Do not put credentials in localStorage or JWT payloads.

## Consequences

Logout and account disablement can invalidate access immediately. Database lookup is required per authenticated request, which is acceptable for the FYP and can later be optimized with careful cache invalidation. OAuth, MFA, password reset, and email verification remain future slices.
