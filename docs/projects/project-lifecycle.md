# Project Lifecycle

Projects start as `active`. Owners may archive them through `POST /api/v1/projects/{projectId}/archive`. Archiving is a lifecycle change, not deletion: authorized members can still read the project, while normal metadata mutations and repeated archive attempts are rejected. Related data is preserved for future reporting and audit.

Restoration is intentionally not implemented yet. Membership invitation, removal, and role changes are also deferred to a later project-membership slice; the current implementation establishes role and policy primitives and creates the owner membership.
