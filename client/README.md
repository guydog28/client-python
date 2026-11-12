# ezclassify-rest-client

HTTP client for the EzClassify REST API. Delegates all operations over HTTP using
[httpx](https://www.python-httpx.org/). No local JS runtime or Node.js required.

## Installation

```bash
pip install ezclassify-rest-client
```

## Usage

```python
from ezclassify_rest_client import EzClassifyClient

with EzClassifyClient("http://localhost:3000") as deployment:
    print(deployment.list_contexts())
    with deployment.context("my-context") as ctx:
        reading = ctx.scheme.validate("LEVEL-A//CTRL-X").result
        print(reading.rendered, reading.valid, reading.input_was_valid)
        for notice in reading.notices:
            print(notice.text, notice.required)
```

Omit the version to let the server choose: the context token's default, or
the newest published. `"latest"` asks for the same thing by name, and a
concrete version such as `"1.0.0"` pins the handle to it.

`validate` is the reader's call: it takes a marking as text or as the facts a
document states and answers whether it stands. `process` is the author's call:
it settles typed text with the facts already chosen and adds corrections,
proven fix paths, the outputs named in `outputs` and the picker options named
in `suggest_for`. `explain` returns the step-by-step trace of a process call.

Every result that describes a marking carries its `notices`, so reading them
costs no second call; the list is empty when the marking carries none.
`ctx.scheme.notices(...)` stays for assertions you assembled yourself and never
put through validate, process or aggregate.

Operations that read a marking take `input_format`, `output_format`, `surface`
and `context` as keyword arguments, named after the wire fields and accepted
only where the operation's request declares them. For a scheme that declares
surfaces, `output_format` and `input_format` also take a view id, a
`surface/view` address, or the id of one of a view's forms. `render` and
`apply_preset` take `output_format` alone.

`EzClassifyClient` represents a deployment. It provides health, Context
discovery, and Context binding. Classification never targets a loose scheme.

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

## Application id

Pass `application_id="case-intake-portal"`, the id your application is
registered under in Studio, when creating `EzClassifyClient` or calling
`connect_context`. The client sends it as the `x-ezclassify-application-id`
header on Context routes and keeps it off health probes. It names the caller for
usage reporting and is not a credential. A blank or malformed id raises
`ValueError` before the HTTP client is created.

## Errors and rate limits

Failures raise `EzClassifyClientError`, which carries `status_code`, the
server's stable `code` and `detail`, and the parsed error body in `payload`.
The server refuses a query parameter or body field an operation does not
declare with a `400` and code `INVALID_INPUT`, and this client sends only what
each operation declares.

A success the contract does not allow raises `MalformedResponseError`, a
subclass of `EzClassifyClientError`: a body that is not JSON, is the wrong
shape, or where a member the contract requires is missing at any depth, or
null where the contract does not allow null. Its `path` says where, in JSONPath, such
as `$.result.errors[0].code`. That points at the server or something in
between, such as a proxy. A `ValueError` is only ever about your own
arguments.

`timeout` (30 seconds by default) bounds each call from start to finish: the
connection, the request, and the whole response body. A server that stalls or
sends its answer a byte at a time cannot hold a call longer. Running out raises
`RequestTimeoutError`, which is an `EzClassifyClientError` and a built-in
`TimeoutError`. A timeout that is not a positive, finite number of seconds,
`None` included, is refused when the client or Context handle is built. Host
name lookup is bounded by your system's resolver settings rather than the
timeout, and through an `https://` proxy to an `https://` server a trickled TLS
record can stretch one read past it. The client honors `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` and `SSL_CERT_DIR` as
httpx does.

Any operation can answer `429`. The exception then carries `retry_after`, the
wait in seconds the server asked for, read from the `Retry-After` header and
otherwise from the body's `retryAfter`. It is `None` on every other error. The
client never waits or retries on its own; sleep for as long as your application
allows and send the request again.

## Response caching

A Context handle is the only cache between your code and the server, and every
EzClassify client caches the same operations the same way. These are kept:
`process`, `validate`, `explain`, `normalize`, `render`, `diff`, `aggregate`,
`aggregate_assertions`, `apply_preset`, `suggest`, `suggest_for_categories`,
`scan`, `describe_concept`, and `access.rules`. Everything else reaches the
server on every call: the scheme resource reads (`summary`, `concepts`,
`categories`, `formats`, `grammar`, `scopes`, `label_presets`), the view,
filter, coverage and notice operations, every guide operation, and
`describe()`.

Every request member is part of the key, so `process` with different `outputs`
or `suggest_for`, or `validate` given text and given facts, are different
requests, while the same arguments in another keyword order are one. Concurrent
identical calls share one HTTP request. A failed request, and a 200 whose body
is missing a member the contract requires, is never kept; the next call asks
again. Each caller gets its own copy of a shared answer, so changing a result
you were handed cannot change what another caller, or a later cached read,
sees.

A concrete Context version is pinned: a published version is immutable, so its
answers are kept until the handle closes or `ctx.clear_cache()` is called, and
only the 500-entry LRU bound evicts them. An omitted version and `"latest"` are
unpinned. Their answers expire after five minutes, two for scans, and an hour
for concept descriptions and access rules. When a response names a new resolved Context version, the handle drops
what it held.

A handle serves one caller. When the server refuses that caller, with a 401 or
with the constant `{"error": "not_found"}` 404 a deployment running
authentication answers unauthenticated requests with, the handle drops every
answer it holds. A 404 about a missing resource leaves them in place. To act as
someone else, build a new handle.

Access checks make a server request every time so each decision is recorded in
the deployment's audit trail. Document audit and access assessment, access
requirements and crosswalk translation are never cached either, whatever the
options.

Pass `disable_cache=True` when creating a handle to send every operation to the
server. `clear_cache()` discards stored operation results without disconnecting.
Calls are synchronous and cannot be canceled individually.

## Describing the Context

`ctx.describe()` reads what the bound Context resolves to right now, which is
the record to keep beside an access decision:

```python
description = ctx.describe()
print(description.version, description.scheme.resolved_version)
for crosswalk in description.crosswalks:
    print(crosswalk.id, crosswalk.version, crosswalk.resolved_version)
```

It reports the composed scheme with its `layers`, the `guides` in precedence
order, the `access` policy, the `crosswalks`, and every held scheme with the
selector that addresses it in `schemes`. Each component carries the version the
Context declares (`version`, possibly `"latest"`) and the concrete one that
answered (`resolved_version`). Each call makes one request. `scheme.scopes()`
returns typed `SchemeScope` entries, each with an `id` and a `label`.

### Marking in another scheme the Context holds

`ctx.scheme` works in the Context's primary scheme. A Context can hold more:
a crosswalk's source and target, or an additional scheme. `ctx.schemes.get`
takes a scheme's key, the `selector` that `describe().schemes` lists, and
returns the same operations bound to that scheme:

```python
description = ctx.describe()
other = next(s for s in description.schemes if "primary" not in s.roles)
result = ctx.schemes.get(other.selector).validate("LEVEL-A")
```

The view sends the key as `?scheme=` on every operation and read. The server
decides which keys exist: a key the Context does not hold answers 404
`scheme_not_found` and the call raises. It never falls back to the primary.
Views are kept per key, and each scheme's answers are cached apart from the
others.

## Access and guide operations

Use the bound `access`, `guide`, `scheme`, `document`, and `crosswalk` groups:

```python
from ezclassify_rest_client import connect_context

ctx = connect_context("http://localhost:3000", context_id="my-context")
decision = ctx.access.check_by_marking("LEVEL-A", {"clearance": "LEVEL_A"})
print(decision.result.granted)
```

## Wire models

Every model reads a server response the forgiving way: a field the server adds
in a later release is ignored, so an older SDK keeps decoding newer responses.
`from_dict` and `model_validate` both work like this.

`from_dict` is also strict about what the contract requires. A member the
OpenAPI document marks required has to be present, at any depth, and may be
null only where the contract allows null; otherwise `from_dict` raises
`pydantic.ValidationError` whose `loc` names the member, such as
`("result", "assessment", "omitted")`. That holds inside the members kept as
plain dictionaries too. A default a model declares for a required member, such
as `Assertion.source`, applies when you build one with keywords, never when
`from_dict` decodes a response. `model_validate` is Pydantic's structural
check and does not look for these members.

`Assertion` is different because you also build it yourself, for example to
pass assertions to an access check. Building one with keywords refuses a
keyword the model does not declare, so a typo fails at once instead of
silently dropping the value before the request is sent:

```python
from ezclassify_rest_client import Assertion

Assertion(category_id="level", concept_id="LOW", source="user")  # ok
Assertion(category_id="level", concept_id="LOW", sourc="user")  # ValidationError
```

That check covers keyword construction only. `Assertion.model_validate(...)`
and `Assertion.from_dict(...)` treat their input as wire data and ignore keys
they do not know, so a misspelled key in a dictionary is dropped without an
error. When you build assertions from your own configuration, unpack it into
the constructor (`Assertion(**config)`) so a misspelled key is caught. The same
applies to `model_copy(update=...)`, which does not validate its keys.

If you type-check with the Pydantic mypy plugin, setting `init_forbid_extra = true`
under `[tool.pydantic-mypy]` catches the same typo before the code runs.

## How the models are maintained

`models.py` is generated from the OpenAPI components and JSON Schemas the
[ezclassify/contracts](https://github.com/ezclassify/contracts) repository publishes, so the models in the wheel match the
wire contract the runtime answers with. Handwritten Python ergonomics and
cross-field validation are isolated in `_model_helpers.py`.

## Dependencies

`httpx`, `httpcore`, `pydantic>=2.14.1,<3` and `typing-extensions>=4.15`.
[`pyproject.toml`](pyproject.toml) is authoritative for the exact floors.
