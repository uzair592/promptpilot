# Authentication Security Considerations

- Passwords are never stored or logged in plaintext; Argon2 is used through `argon2-cffi`.
- Login failure messages are intentionally generic to reduce user enumeration.
- Session tokens are random, opaque, hashed at rest, expiring, and revocable.
- Browser credentials use HTTP-only cookies; production uses `Secure` cookies.
- CSRF risk is reduced with `SameSite=Lax`; state-changing cross-site requests must also be protected with origin checks/CSRF tokens when deployment topology requires it.
- Project authorization is a separate boundary and must be enforced before future project data access.
- Secrets are environment-managed and absent from source, JSON responses, and logs.
- OAuth, password reset, MFA, email verification, billing, and organization management are intentionally deferred.
