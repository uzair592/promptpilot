# AI Pipeline Architecture

| Stage             | Input -> output                              | Nature/dependencies                                        | Failure and persistence                              |
| ----------------- | -------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------- |
| Classification    | request -> task profile                      | probabilistic; LLM or classifier                           | unknown category; persist profile/version            |
| Analysis          | request/profile/context -> analysis          | probabilistic with schema validation                       | timeout/malformed output; persist snapshot           |
| Gap detection     | analysis -> prioritized gaps                 | deterministic policy over analysis, optionally AI-assisted | empty/duplicate gaps; persist gap keys               |
| Questions         | gaps/history -> questions                    | probabilistic generation plus deterministic safety/dedup   | unusable question; reject/retry; persist questions   |
| Answers           | user answer -> accepted context candidate    | deterministic persistence                                  | skipped/invalid answer; preserve message             |
| Documents         | file -> chunks/metadata                      | controlled parsers, optional embedding                     | unsupported/corrupt/oversized; persist status/error  |
| Requirements      | context -> requirements                      | probabilistic extraction plus review                       | uncertain extraction; persist source/certainty       |
| Assembly          | approved sources -> bounded context          | deterministic selection and budget policy                  | no sources/budget conflict; return explainable state |
| Prompt generation | context -> prompt version                    | probabilistic/template hybrid                              | malformed output; validate and keep prior version    |
| Recommendation    | task/model registry -> ranking               | deterministic scoring over metadata/evidence               | stale registry; mark unavailable                     |
| Model run         | prompt/model -> response                     | provider adapter, probabilistic                            | timeout/provider error; persist run state            |
| Evaluation        | response/requirements -> findings            | probabilistic plus deterministic format checks             | unverifiable item; emit uncertain                    |
| Improvement loop  | findings -> revised questions/context/prompt | application orchestration                                  | preserve prior versions and user control             |

Each stage is a typed application port. No stage calls a provider directly from a route or UI component. Provider/model/operation/timestamp/correlation metadata is recorded for each AI operation.
