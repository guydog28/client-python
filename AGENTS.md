# Agent Instructions

## Standards

Read [`STANDARDS.md`](./STANDARDS.md) before any feature, refactor, architectural decision, or task > 30 minutes. These engineering standards apply to you as they do to any contributor. Skip for: quick bug fixes, typos, documentation-only changes.

Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) before any architectural work. It is
the repository's ownership contract for generated code, handwritten seams,
dependency direction, and required boundary gates.

## Wire rules

- Requests are closed. The server answers 400 (`INVALID_INPUT`, with a `detail` such as `query: scheme`) to a query parameter or body field the operation does not declare. A POST operation's only query parameter is the `scheme` selector the scheme operations declare, which a view from `ctx.schemes.get` adds and `ctx.scheme` leaves off; `_post` sends nothing else. A GET sends only the parameters its operation declares, and `test_request_schema_conformance` checks every call against the vendored contract.
- Every operation can answer 400 and 429. `EzClassifyClientError.retry_after` carries a 429's wait, from the `Retry-After` header and otherwise the body's `retryAfter`. The client never sleeps or retries; waiting is the caller's decision.
- Output formats are named `output_format` in Python and `outputFormat` on the wire, on every operation that writes one, `render` and `apply_preset` included.
- No compatibility shims. When the contract drops a parameter or field, the Python argument goes with it.

## Examples

Runnable examples live in [`examples/`](examples/). Each subdirectory is a self-contained demo that exercises the Python client against a real backend.

### [`examples/llm-classify/`](examples/llm-classify/)

CLI demo that classifies a document using the Context-scoped MCP sequence
(`audit_document_markings` → `aggregate_markings`). Two modes:

- **MCP mode** (`--mcp` / `EZCLASSIFY_TRANSPORT=mcp`): spawns the `ezclassify-mcp` runtime binary, licensed and content-configured, as a local subprocess. No LLM API key required; the orchestration is deterministic.
- **REST mode** (default): connects to a running EzClassify REST runtime that serves the Context, with optional `EZCLASSIFY_ACCESS_TOKEN` and `EZCLASSIFY_CONTEXT_TOKEN`. It needs a runtime: the Cedar Valley replay server has no recording for arbitrary document text.

Unit tests in [`examples/llm-classify/tests/`](examples/llm-classify/tests/) cover the classifier workflow, REST client, and CLI entry point using only stdlib mocks, no live server needed. The standalone example tests run as part of `make test`. `make test-mcp-live` requires `MCP_SERVER_PATH` to name the `ezclassify-mcp` binary of a licensed, content-configured runtime and fails if it is absent. `make smoke URL=<server-url>` runs the REST live lane.
