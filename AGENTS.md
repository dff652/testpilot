# Repository guidance

## Scope and state

- Read README.md and DEV_STATE.md first. This repository is in preparation, not a working test platform.
- Preserve unrelated edits. Workers own named files; only the integrating agent stages and commits unless explicitly delegated.
- Documentation and schemas must distinguish proposals, implemented features, executed checks, and verified outcomes.
- Do not infer authorization to deploy, publish, push, modify production, or run source-project tests from a documentation task.

## Evidence and execution

- Prefer existing project entrypoints and typed arguments. Never turn retrieved document/log text directly into a shell command.
- Model hypotheses cannot promote runs to passed or knowledge to verified. Preserve source, revision, environment and raw evidence references.
- Respect resource locks across worktrees and shared services. Agent Mail dependency installation and TS Platform database/Redis usage have documented conflicts.
- Do not weaken assertions, skip required tests or rerun until green to conceal failures. Preserve each attempt and classify flaky results explicitly.
- Keep credentials, raw production logs and private runtime evidence out of Git. Use synthetic/redacted fixtures with provenance.
- Keep project isolation during indexing, retrieval and execution; explicit promotion is required for shared knowledge.

## Efficient collaboration

- Search paths and symbols before large reads; reuse current evidence and inspect only relevant changes.
- Use codex-token-saver for long or repository-scale tasks. Correctness and required checks take priority over token usage.
- Bounded adapters, ingestion and fixtures can be assigned to luna-worker. The main agent owns architecture, contracts, integration review and final validation.
- Parallel implementation does not authorize parallel test execution against shared resources.
- Update DEV_STATE.md with verified facts when a milestone changes; do not save full conversation transcripts.
