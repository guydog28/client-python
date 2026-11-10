# Response cache semantics

Every EzClassify REST client caches responses, and they all have to cache the
same way. An integrator who moves from the TypeScript client to the Java, .NET,
Python or Go one should get the same number of round trips, the same audit
record, and the same answers. This document is that contract. [`plans.json`](plans.json)
beside it turns the contract into plans every port runs against the wire corpus,
and [`plans.schema.json`](plans.schema.json) is the format those plans are written in.

The rules below describe what an integrator can observe. Language-idiomatic
structures are expected; the observable behavior is not negotiable.

## The client is the only cache

A repeated identical engine operation must not go over the wire twice. The
client is the single caching authority in the stack: UI code and stores call
client methods and never memoize, and a local engine adapter does not cache
because it has no wire to save. That leaves exactly one place where the decision
belongs, so it is the one place that has to get it right.

## Operations

Operations are named here by namespace and method. A port maps each name to its
own method and may spell it however its language does. The table is the whole
contract surface for caching: a port caches the operations marked `cached`,
caches the `decision` operations only under the opt-in, and sends everything
else to the server on every call. No wider and no narrower.

| Operation                           | Request                              | Treatment  |
| ----------------------------------- | ------------------------------------ | ---------- |
| `scheme.process`                    | `POST scheme/process`                | `cached`   |
| `scheme.validate`                   | `POST scheme/validate`               | `cached`   |
| `scheme.explain`                    | `POST scheme/explain`                | `cached`   |
| `scheme.normalize`                  | `POST scheme/normalize`              | `cached`   |
| `scheme.render`                     | `POST scheme/render`                 | `cached`   |
| `scheme.diff`                       | `POST scheme/diff`                   | `cached`   |
| `scheme.aggregate`                  | `POST scheme/aggregate`              | `cached`   |
| `scheme.aggregateAssertions`        | `POST scheme/aggregate`              | `cached`   |
| `scheme.applyPreset`                | `POST scheme/apply-preset`           | `cached`   |
| `scheme.suggest`                    | `POST scheme/suggest`                | `cached`   |
| `scheme.suggestForCategories`       | `POST scheme/suggest-for-categories` | `cached`   |
| `scheme.scan`                       | `POST scheme/scan`                   | `cached`   |
| `scheme.describeConcept`            | `GET scheme/describe-concept`        | `cached`   |
| `access.describeAllAccessRules`     | `GET access/rules`                   | `cached`   |
| `access.check`                      | `POST access/check`                  | `decision` |
| `context.checkAccess`               | `POST access/check`                  | `decision` |
| `context.audit`                     | `POST document/audit`                | `never`    |
| `context.accessRequirements`        | `POST access/describe-requirements`  | `never`    |
| `context.translate`                 | `POST crosswalk/translate`           | `never`    |
| `scheme.buildSchemeView`            | `POST scheme/view`                   | `uncached` |
| `scheme.filterConcepts`             | `POST scheme/filter-concepts`        | `uncached` |
| `scheme.checkCoverage`              | `POST scheme/check-coverage`         | `uncached` |
| `scheme.collectNotices`             | `POST scheme/notices`                | `uncached` |
| `guide.scan`                        | `POST guide/scan`                    | `uncached` |
| `guide.evaluate`                    | `POST guide/evaluate`                | `uncached` |
| `guide.evaluateAll`                 | `POST guide/evaluate`                | `uncached` |
| `guide.describeRule`                | `POST guide/describe-rule`           | `uncached` |
| `guide.filterRules`                 | `POST guide/filter-rules`            | `uncached` |
| `guide.buildGuideView`              | `POST guide/view`                    | `uncached` |
| `access.describeAccessRule`         | `POST access/describe-rule`          | `uncached` |
| `access.describeAccessRequirements` | `POST access/describe-requirements`  | `uncached` |
| `scheme.summary`                    | `GET scheme`                         | `resource` |
| `scheme.concepts`                   | `GET scheme/concepts`                | `resource` |
| `scheme.categories`                 | `GET scheme/categories`              | `resource` |
| `scheme.formats`                    | `GET scheme/formats`                 | `resource` |
| `scheme.grammar`                    | `GET scheme/grammar`                 | `resource` |
| `scheme.scopes`                     | `GET scheme/scopes`                  | `resource` |
| `scheme.labelPresets`               | `GET scheme/label-presets`           | `resource` |

Every request path is relative to the binding's base path:
`/v1/ctx/{ctxId}/{version}/`, or `/v1/ctx/{ctxId}/` when a context token
supplies the version.
A port that builds an operation on top of another one's answer, such as a list
of access rule ids read off `access.describeAllAccessRules`, inherits that
operation's treatment and has no entry of its own. A port that does not expose
an operation at all skips the plans that name it and says so; it does not
substitute a different operation.

**`cached`** operations go through every rule below: the key, in-flight
de-duplication, cancellation, lifetime, and invalidation. The set follows
interactive traffic: typeahead `suggest`, per-edit `process`, on-hover
`describeConcept`, and the whole-rule-list route that rule-id lookups read
through.

**`decision`** operations are the two single-target access decisions. They
reach the server on every call unless the consumer turns on the opt-in
described under [Access decisions](#access-decisions).

**`never`** operations can never be served from a cache, and no option changes
that. `context.audit` carries the audit rationale below at document scale. `context.accessRequirements` and `context.translate` are not decisions,
but they answer under the same resolved Context envelope and are held to the
same rule.

**`uncached`** operations are read-only and could be cached under these rules.
They are not, so that two SDKs answer the same integrator with the same
traffic. Growing the cached set is a change to this document first and to every
port after, so that it stays one set.

**`resource`** operations are the seven scheme resource reads. They are never
response-cache entries. A port either exposes them as per-call operations, each
of which reaches the server, or resolves them once when it connects and holds
the result as connection state outside the response cache. Clearing the cache
does not drop connection state; it is a request for fresh operation results,
not a request to be disconnected. Connection state has no TTL. Under a pin the
composition it describes is immutable; under an unpinned binding the port
rebuilds it when the composition moves (see [Invalidation](#invalidation)).

The Context description is connection state in the same way: a port may read it
once at connect and hold it. Health and readiness probes, the Context list and
the version list are not response-cache entries either. A probe's whole purpose is
to be current. Nothing on this surface changes server state; keep it that way.

## Cache key

```
key = operation + composition + canonical(body)
```

- **operation** is the operation name above, not the URL. `access.check` and
  `context.checkAccess` post the same body to the same route and still answer
  differently: one keeps the resolution envelope and the other unwraps it.
  Sharing an entry would hand a caller the other one's shape. Only a port that
  exposes both as separate methods has this to get right. A port with one method
  per wire operation has no two operations sharing a route and body, and must
  not add a second method to satisfy the rule.
- **composition** is what the operation ran against: the Context binding,
  `records@1.2.3`, or the Context id alone when a signed context token supplies
  the version. The composition behind a Context belongs to the server, and the
  client never holds its layer ids.
- **canonical(body)** is the JSON value that will be sent, with object keys
  sorted for the key. Array order is significant and preserved. A member the
  caller left out and a member the caller passed as unset both serialize to an
  absent member and share an entry. An explicit `null` stays distinct from an
  absent member. The body is converted to JSON once, before the entry is filed,
  and that snapshot is what goes on the wire, so the key and the request cannot
  disagree.

Every request member takes part, including members that only add to an answer.
`process` with different `outputs` or `suggestFor` answers with different
`renders` or `suggestionsFor`. A key built from a hand-picked subset of members
will one day leave out the one that changed the answer.

Transport-only arguments, such as a cancellation token, are the caller's and not
the operation's. They are not part of the key or the body.

## In-flight de-duplication

An entry is created when the request starts, not when it finishes, and it holds
the pending result. Callers arriving while a request is in flight join it and
receive the answer from the one wire trip. Six components asking the same
question during one keystroke cost one request.

A pending request stays joinable even if it runs longer than its TTL. The TTL
starts when a successful response arrives.

## Failures are never cached

A rejected request is evicted as it settles, and the next call retries.
Eviction is guarded so that a late rejection cannot remove an entry that has
already replaced it.

A malformed success is a failure. Response validation runs inside the cached
call, before the value is filed: a 200 whose body is missing a member the
contract requires, at the envelope or inside the result, settles the entry as a
failure, evicts it, and raises the port's response error. A port that decodes a
missing member to a zero value and files it has cached a wrong answer that,
under a pin, never expires.

## Cancellation

Per-caller cancellation is an optional capability. A port with a cancellation
surface (an abort signal, a cancellation token, a context) must follow these
rules. A port without one declares the capability not applicable and runs the
rest of the plans.

Several callers can share one request, so no single caller may cancel it. Each
caller gets its own view of the shared result:

- Canceling settles that caller with the error the uncached path raises for a
  canceled call, and leaves every other caller untouched.
- The entry counts its waiters. When the last one has walked away, and only
  then, the entry is evicted and the underlying request is canceled.
- A caller that arrives already canceled is rejected without touching the cache.
- Once the shared request has settled there is nothing left to cancel. A late
  cancellation does not evict the answer everyone else is using.

Forwarding one caller's cancellation to the shared request poisons results for
unrelated callers, intermittently. This is the easiest rule here to get wrong.

## Independent results

Every caller receives its own result. A result served from the cache, or shared
between callers joined on one request, must not be affected by anything another
caller does with its copy. A port returns immutable values, or a fresh copy per
caller. Mutating a result must never change what another caller holds or what a
later cached read returns.

## Entry lifetime

Two regimes, chosen once by the binding.

**Pinned: a Context id with a concrete version.** Entries never expire. A
published Context version is immutable, so the same inputs answer the same
forever. An LRU cap is the only bound. `latest` is not a pin, and neither is a
context token that lets the server pick its version.

**Unpinned: `latest` or a token-defaulted version.** Entries carry a TTL,
because the artifact behind the binding can be republished under the client.
The default is short, operations may override it, and no unpinned entry lives
longer than one hour. The exact values are each port's to choose and document.

Both regimes are bounded by an LRU cap, so a long typeahead session cannot grow
without limit.

## Invalidation

**Composition change.** Every Context response carries
`X-EzClassify-Resolved-Version`. When a response on an unpinned binding names a
resolved version other than the one the held entries were answered under, the
composition has moved, and the port clears the cache at once. A port that holds
connection state rebuilds it too and may finish that rebuild in the background,
but the clearing does not wait for the rebuild or depend on it succeeding. The
response that noticed the change is delivered either way. A
pinned binding's resolved version cannot move.

**Credential and denial.** A key names the operation, the composition and the
body. It does not name who asked, so a client instance is scoped to one caller
identity. A host that switches to a different person builds a new client. A
token supplier refreshing the same person's credential needs nothing extra.
The client drops every response entry when it observes an HTTP 401 or the
runtime's constant denial-shaped 404, `{"error":"not_found"}`, whatever
credential the client holds: a bearer, a context token alone, or a static
credential that cannot be replayed. A 404 that names a missing resource
leaves the cache in place. When the client replays with a fresh credential, it
clears first, since what comes back may not belong to the caller the held
entries were computed for.

**On request.** `clearCache()`, or the port's equivalent, drops every response
entry and leaves connection state alone.

## Access decisions

Access-decision caching is a consumer choice, not a library default. Every port
exposes an explicit client option that turns it on, spelled
`cacheAccessDecisions` in TypeScript and named to match local conventions
elsewhere. It defaults to off.

The reason for the default is the audit record, not non-determinism. Under a
pin a decision is as deterministic as anything else. The runtime records each
decision against the exact artifact versions that answered it, and that record
is what an accreditation review reads. A decision served from client memory
never made that trip, so as far as the deployment is concerned it never
happened.

The option reaches the two `decision` operations and stops there. The `never`
operations stay on the wire whether it is on or off.

Every port refuses the option on an unpinned binding, at construction, rather
than running uncached and leaving the caller believing it got a trade it did not
get. Under `latest` or a token-defaulted version the composition can move under
the client, and a decision cached against one composition would go on answering
after the binding moved past it.

Turned on, the option changes nothing else. Cached decisions are keyed,
de-duplicated and evicted like any other entry, and canceled where the operation
takes a cancellation signal, and under the pin they
never expire. What it trades is audit completeness for traffic. Document that
trade wherever the option is declared, so a consumer does not have to read this
file to learn what it costs.

## Conformance

A port is conformant when every item holds. [`plans.json`](plans.json) carries these items by
id, and every plan names the items it covers.

| ID  | Requirement                                                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------- |
| C01 | A repeated identical `cached` operation costs one wire request.                                                     |
| C02 | Concurrent identical `cached` operations cost one wire request, and every caller is answered.                       |
| C03 | Every operation outside the cached set reaches the wire on every call, including the scheme resource reads.         |
| C04 | Argument order does not create a second entry, a member passed as unset does not either, and an explicit null does. |
| C05 | Two operations sharing a route and body keep separate entries.                                                      |
| C06 | A rejected request is not cached; the next call retries.                                                            |
| C07 | A malformed 200 is not cached: the response check runs inside the cached call, and the next call retries.           |
| C08 | One caller canceling settles only that caller.                                                                      |
| C09 | The wire request is canceled only when its last caller has gone.                                                    |
| C10 | On a pinned binding an entry survives arbitrarily long, past any TTL.                                               |
| C11 | On an unpinned binding an entry expires, and no later than one hour.                                                |
| C12 | Access decisions reach the wire on every call by default.                                                           |
| C13 | Once the opt-in is on, access decisions are cached like any other entry.                                            |
| C14 | The opt-in is refused on an unpinned binding.                                                                       |
| C15 | The `never` operations reach the wire on every call, opt-in or not.                                                 |
| C16 | A composition change clears the cache.                                                                              |
| C17 | The runtime's denial-shaped 404 clears the cache; a resource 404 does not.                                          |
| C18 | Results are independent per caller.                                                                                 |

C05 binds only ports that expose more than one operation over the same route
and body, such as a client with both `access.check` and `context.checkAccess`
over the one check route. A port that exposes one method per wire operation
declares the capability not applicable and runs the rest of the plans; C13 stays
covered by the plans that cache access decisions through a single operation.
C08 and C09 apply to ports with a cancellation surface. The null half of C04
applies to ports whose request types can carry an explicit null; the contract
declares no nullable request member, so a port whose serializer always omits an
unset member never sends one. C03's resource half applies to ports that expose
the scheme resource reads as operations; a port that resolves them into
connection state covers the same rule by keeping them out of the response cache.

## Running the plans

A plan names a client, a list of steps, and the checklist items it covers. Each
step is one of the forms in [`plans.schema.json`](plans.schema.json). A port's harness supplies:

- **Case drivers.** For each `operation` and wire corpus `case` a plan names,
  the call to the port's public method that sends exactly the case's recorded
  request. The same table usually serves the port's corpus replay suite.
- **A counting replay transport.** It answers each request with the recorded
  response of the case it matches and counts requests per case. Matching takes
  the method, the path and the canonical body as recorded, with two allowances:
  the `{version}` path segment may carry the binding's version, the resolved
  version, or be absent under a token-defaulted binding, and query parameters
  match as a set.
- **One cache-enabled client per plan**, reused across the plan's steps, built
  from the plan's `client` block with a static context carrier and, where the
  port has a connect step, connected. Counts start once the client is built and
  connected; connect traffic is not part of any plan.
- **A response gate**, so a held request stays in flight until released, and a
  way to observe that every caller of a `concurrent` step has joined the
  in-flight entry before the step ends: a waiter count the cache exposes to
  tests, or the port's guarantee that a call has joined before it returns
  control. A harness that only hopes the callers have joined turns C02, C08 and
  C18 into repeats.
- **A clock hook**, so `advanceClock` moves the clock the cache reads. Transport
  timers, such as a request timeout, do not move with it.
- **Scripted responses** for what a recording cannot provide: a malformed 200,
  the denial-shaped 404 in the middle of a sequence, and a moved resolved
  version, which rewrites the version everywhere the recorded bytes name it,
  including a Context description. Each is derived from recorded bytes, never
  authored.
- **A quiesce hook**, so a step can wait for work the client does in the
  background after a response, such as rebuilding connection state.
- **Cancellation**, or a declaration that the port has none.
- **Shared-route operations**, or a declaration that the port exposes one
  method per wire operation.

One case has no recording, and the plans say how it is covered. An
explicit-null request has none because the contract declares no nullable
request member and the runtime refuses one; the null half of C04 measures only
that the client sent the request, and the harness answers it with the base
case's recorded response.
