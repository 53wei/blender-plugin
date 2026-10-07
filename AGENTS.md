# Codex Working Contract

1. Read `docs/DEVELOPMENT_SPEC.md` and the latest ADR before writing code.
2. Keep work inside the current milestone and do not expand scope without a request.
3. M1 must not add an LLM, HTTP, chat UI, or mesh-editing product feature.
4. Add or update tests for each domain behavior before connecting it to Blender UI.
5. Never replace the action schema with free-form Python execution.
6. Never weaken the verifier to make a failing test pass; explain and fix the cause.
7. Route every Blender state change through the transaction and executor layers.
8. Update schemas, tests, and documentation together when fields, actions, or error codes change.
9. Return an explicit unsupported error for geometry the implementation cannot handle reliably.
10. Report what changed, what was tested, and which risks remain.
