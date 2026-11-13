# llm-classify

Classify a document the way an LLM agent would: by driving the EzClassify
MCP tool-use sequence one call at a time.

```
audit_document_markings  find the overall marking and every part marking, and judge each one
aggregate_markings       compute the overall marking the valid parts require
```

The demo runs against the `cedar-valley` Context by default, a fictional school
district policy for teaching. Its long form (`CONFIDENTIAL`) marks a whole document and its
short form in parentheses (`(P)`, `(C)`, `(I)`) marks a part. The audit needs a
Context whose scheme has both a whole form and a part form; a scheme with only
a whole form reads every marking as a whole and finds no parts.

The demo reads markings someone else wrote, so it audits them, the reader's
call. Process is the call for helping someone write a marking.

The report lists the part markings found, any that failed validation and why,
the overall marking the author wrote and whether it covers the parts, the
overall marking the parts require, and the handling notices on that result.

## Before you start

This example sends your own document text to a runtime. The Cedar Valley replay
server answers only requests recorded in advance, so it cannot audit this memo:
it returns a 501 diagnostic. Use a runtime that serves the `cedar-valley`
Context. To see the Python client working before you have one, start with the
[Quickstart](../../README.md#quickstart), which runs against the replay server.

You need Python 3.11 or newer and the SDK:

```sh
pip install -r requirements.txt
```

## Run it against your runtime

Your runtime administrator gives you the runtime URL and, for a secured
deployment, two credentials: a caller token and a signed Context token. A
runtime started on your machine listens on `http://localhost:3000`, which is
the default for `--server`. Export the tokens if your deployment asks for them:

```sh
export EZCLASSIFY_ACCESS_TOKEN=<caller identity token>
export EZCLASSIFY_CONTEXT_TOKEN=<signed Context token>
```

Then audit the sample memo. `--context` or `EZCLASSIFY_CONTEXT_ID` picks the
published Context (default `cedar-valley`), and `--context-version` or
`EZCLASSIFY_CONTEXT_VERSION` picks the version. Omit the version to let the
server choose: the Context token's default, or the newest published:

```sh
python3 -m main --server https://runtime.example.com --file sample.txt
```

Classify inline text instead of a file:

```sh
python3 -m main --server https://runtime.example.com --text $'CONFIDENTIAL\n\n(P) Route map posted in March.\n\nCONFIDENTIAL'
```

Each step prints as it runs, so you can watch the audit call and the aggregate
call it feeds. Add `--quiet` to print only the final report.

For the sample memo the report finds four part markings and no validation
issues. The authored overall marking is `CONFIDENTIAL` and it covers the parts.
The parts also require `CONFIDENTIAL`, and the report lists the handling
notices on that result. It also reports the procedural gap the scheme infers,
which the memo never states.

## Run it through MCP

MCP mode spawns the `ezclassify-mcp` binary from your runtime's release archive
instead of calling the REST API. Put the binary on `PATH` or name it with
`MCP_SERVER_PATH`. The runtime needs a valid license and a signed content
bundle, which it reads from the environment the example passes through:

```sh
export EZCLASSIFY_ARTIFACT_DIR=/var/lib/ezclassify
export EZCLASSIFY_LICENSE_LOCATION=/etc/ezclassify/license.ezl
export EZCLASSIFY_BUNDLE_DIR=/etc/ezclassify/bundles
export EZCLASSIFY_CALLER_ORGANIZATION_ID=<your organization id>
```

Then run the example:

```sh
python3 -m main --file sample.txt --mcp
```

The output is the same report.

## How it is wired

| File | Role |
|---|---|
| [`main.py`](main.py) | CLI entry point and argument parsing |
| [`classifier.py`](classifier.py) | The audit -> aggregate workflow and the report |
| [`mcp_client.py`](mcp_client.py) | MCP backend that spawns and speaks to the licensed runtime |
| [`client.py`](client.py) | Tiny adapter over the published Python Context client |
| [`sample.txt`](sample.txt) | A fictional Cedar Valley memo with an overall marking and four part markings |

Both backends satisfy the same small `ClassifyClient` protocol (`audit`,
`aggregate`), so the workflow code does not care which one is in
use.

## Tests

The unit tests stub the client, so they run without a live server:

```sh
pytest tests/
```

The standalone example tests run as part of the repository's `make test`.
Run the eleven MCP acceptance cases separately with `make test-mcp-live` from
the repository root. `MCP_SERVER_PATH` must name the `ezclassify-mcp` binary of
an already licensed, content-configured runtime with the published Context
selected by the example.
Supply a signed authorization carrier only when the deployment requires one.

For a deployment using Context-token authorization, set `EZCLASSIFY_CONTEXT_TOKEN`
to the signed carrier supplied by your runtime administrator. The example sends
it as `params._meta.ezclassifyContextToken` on each tool call. Standalone and
organization-authorized deployments do not require a Context token.
