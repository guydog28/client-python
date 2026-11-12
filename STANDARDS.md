# Engineering Standards

Design, code quality, testing, and decision-making rules for this project. All contributors follow these.

---

## Design

- **Readability first; performance when it matters.** If a less-readable path has significant performance gains, take it, but document why with a comment explaining the tradeoff.
- **Purist design over quick fixes.** Invest in correct abstractions upfront. Architectural debt that compounds should be prevented, not queued.
- **Interfaces over concrete types.** Depend on interfaces and abstractions, never concrete classes. Factories accept implementations; they don't construct them across layers.
- **Own the blast radius of your changes.** When you change something, know the full ripple and address it in the same PR. Don't leave broken dependents "to fix later" without an explicit decision to do so.

## Code Quality

- **Docstrings on all public API.** Every public module, class, and function gets a docstring for purpose and contract, not a restatement of what the code does. Describe arguments, return values, and the exceptions that can propagate.

- **Comments explain WHY, not WHAT.** Only comment when the next developer might not understand why you didn't do the obvious thing. Explain constraints, workarounds, hidden dependencies, not logic flow.

- **Zero trust at public boundaries.** Validate all inputs on the public API and all external API responses. Trust internal calls between private methods. Fail fast with clear errors at boundaries.
- **Type hints everywhere.** Annotate public signatures. Remove unused imports. Prefix intentionally unused parameters with `_`. Do not paper over type errors with `# type: ignore` unless the reason is documented inline.
- **Generated code is not hand-edited.** The Pydantic models in [`client/ezclassify_rest_client/models.py`](client/ezclassify_rest_client/models.py) are regenerated from the spec (`make regen`). Change the generator or the spec, never the output file.

## Testing

- **Order: Contract → Tests → Implementation.** Write the docstring contract first, tests second, implementation third. Tests are specs, not afterthoughts.
- **One responsibility per method.** Single purpose, clear `@param`/`@returns`, no side effects unless that's the method's entire point.
- **Test behavior, not coverage percentages.** Each test verifies a specific path: happy path, bad path, or defensive guard. Skip tests that add no value.
- **Separate test types strictly.**
  - **Unit:** import from source files; test functions in isolation
  - **Integration:** import from the public package API only; use real classes, no mocks of internal modules
  - **E2e:** run against a real REST API server (the live-smoke and conformance suites); run only in their explicit lanes, and fail with a reason when no server is available
- **Bug fixes require regression tests.** Every fix needs a test that fails before the fix and passes after. No exceptions.

## Decision-Making

- **Stable contracts, incremental changes.** Preserve published API compatibility. Prefer incremental, reversible changes and follow semantic versioning for breaking changes.
- **Inline small debt, backlog large debt.** Found debt under 30 min effort: fix inline. Larger refactors, dependency upgrades, or architectural changes: log to backlog, don't auto-execute.
- **Don't let tasks balloon.** If you discover work that significantly exceeds the original scope, stop, log it, and stay on scope. Surface it for explicit prioritization.
