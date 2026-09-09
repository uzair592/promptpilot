# Project Architecture

Projects are the first product aggregate built on top of authentication. Routes delegate to project services; services use SQLAlchemy repositories/models and a single authorization policy. The owner relationship is explicit in `projects.owner_id` and `project_members`.

```text
project route -> project service -> Project/ProjectMember repository boundary
                       |
                       +-> project authorization policy
                       +-> transaction: project + owner membership
```

The project slice does not know about conversations, AI, prompts, documents, or context. Those modules will depend on the reusable project access context in later slices.
