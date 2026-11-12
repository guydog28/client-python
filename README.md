# <img src="assets/icon.svg" alt="" width="32"> EzClassify Python SDK

[![CI](https://github.com/ezclassify/client-python/actions/workflows/ci.yml/badge.svg)](https://github.com/ezclassify/client-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ezclassify-rest-client?label=ezclassify-rest-client)](https://pypi.org/project/ezclassify-rest-client/)
[![license: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://pypi.org/project/ezclassify-rest-client/)

Apache-licensed HTTP client for a licensed EzClassify REST runtime. It contains wire models and client ergonomics, not the proprietary engine or enterprise content. One PyPI package is provided: `ezclassify-rest-client`, which carries both the client and the wire models.

The [ezclassify/contracts](https://github.com/ezclassify/contracts) repository owns
document and wire types; EzClassify Runtime owns
marking and access evaluation. This client owns HTTP transport, response decoding, caching, and
language-native conveniences. Evaluation operations address a published Context;
health and Context discovery use the deployment endpoint.

## Supported runtimes

Python 3.11 or newer. Use a virtual environment to keep application dependencies
isolated from system packages.

## Install

```sh
pip install ezclassify-rest-client
```

Python 3.11+. The SDK ships client-only: use `EzClassifyClient` against a running REST API server.

## Quickstart

Start with the Cedar Valley replay server. It answers recorded requests for a
fictional school-district Context, so you can see your integration work before
you have a runtime, a license, or credentials. Node.js 22 or newer is needed
for the replay server only; your application stays Python.

```sh
npx @ezclassify/conformance-server --scenario cedar-valley --port 4010
```

Then connect the normal client to it:

```python
from ezclassify_rest_client import connect_context

with connect_context(
    "http://127.0.0.1:4010", context_id="cedar-valley", context_version="1.0.0"
) as ctx:
    marking = ctx.scheme.process("INTERNAL").result
    print(marking.rendered, marking.valid)

    decision = ctx.access.check_by_marking("CONFIDENTIAL", {}).result
    print("granted:", decision.granted)
    for rule in decision.rules:
        print(f"  {rule.name}: {rule.granted}")
```

```text
INTERNAL True
granted: False
  Protection clearance: False
  Sensitive content permissions: True
  Permitted school: True
  Recipient organization: False
```

The server replays recordings, so it only knows a finite set of requests:
Context `cedar-valley` version `1.0.0`, and inputs such as `PUBLIC`, `INTERNAL`
and `CONFIDENTIAL`. The
[scenario catalog](https://github.com/ezclassify/contracts/tree/main/packages/conformance-server/scenarios/cedar-valley#readme)
lists every supported request. Anything else gets a 501 diagnostic instead of an
invented answer. It requires no credentials by default; add `--auth simulated`
to test how your code handles a missing or wrong credential.

### Swap to your runtime

Change the base URL and add real credentials. The calls stay the same. Obtain
the REST endpoint and credentials from your EzClassify runtime administrator.
A secured deployment reads the caller identity from `access_token` and Context
authorization from `context_token`; leave either out when the deployment does
not require it.

```python
import os

from ezclassify_rest_client import EzClassifyClient, RestClientCredentials

credentials = RestClientCredentials(
    access_token=os.environ["EZCLASSIFY_ACCESS_TOKEN"],
    context_token=os.environ["EZCLASSIFY_CONTEXT_TOKEN"],
)

with EzClassifyClient(
    "https://runtime.example.com", credentials=credentials
) as deployment:
    print(deployment.list_contexts())
    print(deployment.list_context_versions("cedar-valley"))
    with deployment.context("cedar-valley") as ctx:
        reading = ctx.scheme.validate("confidential").result
        print(reading.rendered, reading.valid, reading.input_was_valid)
        decision = ctx.access.check_by_marking(
            "CONFIDENTIAL", {"clearance": "INTERNAL"}
        )
        print(decision.result.granted)
```

Use any Context your runtime publishes in place of `cedar-valley`. Omit the
version to let the server choose: the context token's default, or the newest
published. Pass one, such as `"1.0.0"`, to pin it. The concrete Context version
resolved by the server is on `ctx.resolved_version`.
Operation groups are `ctx.scheme`, `ctx.guide`, `ctx.access`, `ctx.document`,
and `ctx.crosswalk`. `ctx.scheme` is the Context's primary scheme;
`ctx.schemes.get(key)` is any other scheme the Context holds. There is
intentionally no loose scheme-addressed mode.

### Naming your application

Pass the id your application is registered under in Studio as `application_id`.
The runtime counts requests per application and reports usage to Studio. The id
is not a credential and authorizes nothing; a request without one, or with an id
the deployment has not registered, is served the same way.

```python
with EzClassifyClient(
    "https://runtime.example.com",
    application_id="case-intake-portal",
) as deployment:
    with deployment.context("cedar-valley") as ctx:
        print(ctx.describe().version)
```

The client sends it as the `x-ezclassify-application-id` header on Context
routes and omits it from health probes. An id is 1 to 128 printable ASCII characters (`!` to `~`, no spaces); anything
else raises `ValueError` naming the rule before a connection is created.
`connect_context` takes the same option. When a user bearer is required, supply
it through `RestClientCredentials(access_token=...)`; the SDK does not sign
users in.

## API surface

| Operation | Surface |
|---|---|
| Context discovery and health | `deployment.list_contexts()`, `list_context_versions()`, `ping()` |
| validate / process / explain / aggregate / suggest / suggest_for_categories / scan | `ctx.scheme.*` |
| scheme concepts, categories, formats, label presets and scopes | `ctx.scheme.concepts()`, `categories()`, `formats()`, `label_presets()`, `scopes()` |
| what the Context resolves to, with declared and resolved versions | `ctx.describe()` |
| access check / requirements / rules | `ctx.access.*` |
| guide scan / evaluate / rules | `ctx.guide.*` |
| document audit / access assessment | `ctx.document.*` |
| directional translation, and the crosswalks the Context holds | `ctx.crosswalk.translate(...)`, `ctx.crosswalk.describe()` |

### Reading a marking and writing one

`validate` is the reader's call: displaying a marking, gating on it, storing
it, or handing its facts to an access check or a rollup. It takes the marking
as text, or as the facts a document states, and answers whether it stands once
settled (`valid`) and whether it was right as written (`input_was_valid`),
with the errors, the rendering and how recognition read it.

`process` is the author's call, for a composer or editor that helps someone
write a marking. It settles the typed text together with the facts already
chosen, and adds the corrections, the proven fix paths, a rendering for each
output named in `outputs`, and picker options for each category named in
`suggest_for`. `explain` takes the same request and returns the step-by-step
trace instead.

```python
with deployment.context("cedar-valley") as ctx:
    reading = ctx.scheme.validate("confidential").result
    print(reading.valid, reading.input_was_valid, reading.recognition)

    draft = ctx.scheme.process(
        "confidential", outputs=["default", "short"], suggest_for=["level"]
    ).result
    print(draft.renders["short"]["rendered"], draft.proposed_fixes)
    if draft.suggestions_for is not None:
        print([option.label for option in draft.suggestions_for["level"].suggestions])

    trace = ctx.scheme.explain("confidential").result
    for entry in trace.entries:
        print(entry.stage, entry.action, entry.detail)
```

`renders` holds the outputs you name and nothing else, and `suggestions_for` is
`None` unless you name categories. `suggest` answers picker options alone, and
`suggest_for_categories` answers several categories in one round trip, keyed by
category id. Errors about text the engine could not read may carry
`did_you_mean`, the ids of the concepts it may have been meant as.

`suggest` takes partial text or `assertions` containing stated facts, exactly
one input. Empty text and an empty fact list are valid inputs. `input_format`
only accompanies text, on both `suggest` and `validate`; fact inputs accept
`output_format` and `surface` without a text format.

```python
options = ctx.scheme.suggest(assertions=[], surface="classification").result
```

Assertion `source` is an open string. The SDK forwards custom labels without
assigning meaning to them. Core processing
recognizes `infer`, `default`, `context`, and `repair` with `source_rule` as
previously derived facts; other labels, including `parse`, `user` and `stated`,
remain authored input. The engine owns settling and derivation.

### Formats, views and surfaces

Scheme operations take their format choices as keyword arguments named after
the wire fields, and each takes only the options its request declares, so
`diff` takes `input_format` alone. `render` and `apply_preset` only produce
output, so they take `output_format` alone.

- `output_format` picks what the result is written in: a format id, or for a
  scheme that declares surfaces, a view id, a `surface/view` address, or the
  id of a form exactly one view names. Leave it out and you get the scheme's
  default. For a scheme that declares surfaces, that is each surface's default
  view for the marking's role, so a part and a whole can come back in
  different views.
- `input_format` says what the text is read as: a format id, or a view id, a
  `surface/view` address or one of a view's forms. Leave it out and
  recognition works it out. `recognition["inputFormat"]` reports what the text
  was read as: the format, or for a scheme that declares surfaces, the
  `surface/view` address of the view, with `recognition["role"]` saying
  whether it is spelled as a whole or a part.
- `surface` names which of the scheme's scopes the input is, for a fragment
  such as a portion. Leave it out and the input is judged as a whole marking.
- `context` is forwarded to the engine. A role given there, such as
  `{"role": "part"}`, is the role the marking is judged and written in.

### Errors and rate limits

Errors raise `EzClassifyClientError` with the HTTP status code when one was
received, the server's stable `code` and `detail` when it sent them, and the
parsed error body in `payload`.

Requests are closed: the server answers `400` with code `INVALID_INPUT` to a
query parameter or body field the operation does not declare, and `detail`
names it, such as `query: scheme`. This client sends only what each operation
declares.

A success the contract does not allow raises `MalformedResponseError`, a
subclass of `EzClassifyClientError` whose `path` names the member, such as
`$.result.errors[0].code`. That covers a body that is not JSON, the wrong shape,
or one where a member the contract requires is missing, or null where null is
not allowed. Such an answer is never cached. `ValueError` is reserved for your
own arguments.

Every call finishes within the client's `timeout`, 30 seconds unless you pass
another. It is one deadline for the whole request: waiting for a connection,
connecting, sending, and reading the status, headers and the entire body. A
server that stalls or trickles its answer cannot hold a call past it. A call
that runs out raises `RequestTimeoutError`, a subclass of both
`EzClassifyClientError` and the built-in `TimeoutError`. The timeout must be a
positive, finite number of seconds; `None`, zero, a negative number or infinity
raises when the client is built. Two waits are outside it: looking up the
server's host name, which your system's resolver settings bound, and, through
an `https://` proxy to an `https://` server, a server that trickles a TLS record
can stretch one read past the deadline.

Any operation can answer `429` when the rate limiter trips. The exception
carries the wait the server asked for in `retry_after`, in seconds, from the
`Retry-After` header and otherwise from the body's `retryAfter`; it is `None`
on every other error. The client never sleeps or retries by itself. You choose
whether to wait and for how long:

```python
import time

from ezclassify_rest_client import EzClassifyClientError

try:
    reading = ctx.scheme.validate("confidential").result
except EzClassifyClientError as error:
    if error.status_code != 429 or error.retry_after is None:
        raise
    time.sleep(min(error.retry_after, 30))  # your own upper bound
    reading = ctx.scheme.validate("confidential").result
```

## Versioning

SDK `major.minor` tracks the rest-api `major.minor`; patch versions may drift. `client.engine_spec_version()` is the spec version this SDK was built against, `client.ping()` returns the live server version, and the first mismatch logs a `WARNING` on the `ezclassify_rest_client.client` logger.

## Examples

Runnable examples live in [`examples/`](examples/). The
[`llm-classify`](examples/llm-classify/) demo audits a document with the
`audit_document_markings` and `aggregate_markings` sequence and prints a
classification report. It sends arbitrary document text, which the Cedar Valley
replay server has no recording for, so it needs a runtime that serves the
`cedar-valley` Context. Point it at yours and supply the credentials your
administrator issued:

```sh
cd examples/llm-classify
export EZCLASSIFY_ACCESS_TOKEN=<caller identity token>
export EZCLASSIFY_CONTEXT_TOKEN=<signed Context token>
python3 -m main --server https://runtime.example.com --file sample.txt
```

Leave the tokens out if your runtime asks for none. Add `--mcp` to spawn a
licensed, content-configured `@ezclassify/mcp` runtime instead. The example's
README shows the report and both modes.

## Integration testing

The replay server from the [Quickstart](#quickstart) also exercises your error
handling. Your code decides what to log and when to retry; the recordings let you
check that without a runtime.

```python
from ezclassify_rest_client import connect_context, EzClassifyClientError

try:
    with connect_context(
        "http://127.0.0.1:4010", context_id="cedar-valley", context_version="1.0.0"
    ) as ctx:
        decision = ctx.access.check_by_marking("CONFIDENTIAL", {}).result
        print(
            {
                "granted": decision.granted,
                "rules": [
                    {
                        "rule": rule.rule.rule_id,
                        "granted": rule.granted,
                        "reason": rule.reason,
                    }
                    for rule in decision.rules
                ],
            }
        )
except EzClassifyClientError as error:
    print("Integration request failed", error.status_code, error)
```

The example logs the outcome and rule explanations without copying subject
attributes or credentials into the log. In your backend, derive attributes
from trusted identity data and add your application's correlation ID and
resource reference. Apply your log retention and redaction policy to returned
explanations too. A denied access decision is a successful response with
`granted: false`; handle transport or authentication failures separately.

Restart with `--scenario transient-error`, `rate-limit`, `unavailable`,
`slow-response`, `disconnected`, `malformed-json`, or `malformed-envelope` to
exercise failures on the recorded process request. Clear the client response
cache or create a new client between runs so an earlier answer does not hide
the scenario. These recordings test your integration, not the correctness of a
production authorization policy.

## Reporting issues

Issues are tracked centrally for the whole EzClassify family. File bugs and feature requests, or ask a question, at [github.com/ezclassify/ezclassify](https://github.com/ezclassify/ezclassify) (Issues and Discussions). For vulnerabilities, follow the [security policy](https://github.com/ezclassify/ezclassify/blob/main/SECURITY.md) instead.

## Links

Website and runtime access: [ezclassify.com](https://ezclassify.com) · Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Security: [policy](https://github.com/ezclassify/ezclassify/blob/main/SECURITY.md) · Engineering standards: [STANDARDS.md](./STANDARDS.md)

## License

[Apache License 2.0](LICENSE) © EzClassify, LLC
