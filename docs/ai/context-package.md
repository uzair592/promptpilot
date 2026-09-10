# Context Package

`ContextPackage` keeps memory, answers, requirements, constraints, and document
context separate. Every selected item carries provenance and a user-facing reason;
`sources` provides a compact audit view. `omitted_items` explains lower-priority
or over-budget candidates without exposing their content. `used_budget` is the
sum of selected content lengths and never exceeds `budget`.

The package keeps project memory, user answers, document context, requirements, constraints, selected sources, budget, and omission metadata in separate typed sections. It is computed dynamically and is not stored as a second memory system.
