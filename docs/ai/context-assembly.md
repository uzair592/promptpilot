# Context Assembly

`ContextAssembler` combines active Project Memory with top-ranked project document chunks. Memory is included first because user-provided structured facts are authoritative; chunks are included by lexical relevance until the character budget is reached. Omitted chunks are counted and selected sources retain provenance.
