# Architecture

This repository contains the EzClassify Python SDK. It adapts the public REST
contract to Python; EzClassify Runtime evaluates marking operations and composes
Contexts. It publishes two packages
with one-way dependencies: `ezclassify-contract` and
`ezclassify-rest-client`. The repository-root package is only the
conformance test harness; it is not a third implementation package.

## Sources of truth

- The [ezclassify/contracts](https://github.com/ezclassify/contracts) repository owns
  the canonical wire types, JSON Schemas, OpenAPI, and conformance corpus.
  EzClassify Runtime owns engine behavior and Context composition.
- [`vendor/spec/`](vendor/spec/) is this repository's read-only mirror of those contracts.
  The spec bot is its sole writer, and [`vendor/spec/MANIFEST.json`](vendor/spec/MANIFEST.json) records the
  upstream provenance (`contractsSha` plus the `sourcePackages` it was built
  from), contract digests, generator inputs, and committed generated outputs.
  Do not edit the mirror by hand.
- [`api-surface.txt`](api-surface.txt) is the reviewed public API golden for both published
  packages. Conformance plans, recordings, fixtures, and semantic cases live
  under their named directories in [`vendor/spec/`](vendor/spec/); the repository-root
  [`tests/`](tests/) replay them through public adapters.

## Generated code

- [`scripts/gen.mjs`](scripts/gen.mjs) is the manifest-pinned generator entrypoint. It verifies
  the hash of its complete implementation, [`scripts/gen_models.py`](scripts/gen_models.py), before
  invoking it.
- [`scripts/gen_models.py`](scripts/gen_models.py) reads [`vendor/spec/openapi.yaml`](vendor/spec/openapi.yaml) and every
  `vendor/spec/json-schemas/*.schema.json`. Its sole committed output is
  [`types/ezclassify_contract/models.py`](types/ezclassify_contract/models.py), as recorded in
  [`vendor/spec/MANIFEST.json`](vendor/spec/MANIFEST.json).
- [`types/ezclassify_contract/models.py`](types/ezclassify_contract/models.py) is the only public module that
  declares the generated wire models. Its first line carries the contract
  digest and `DO NOT EDIT` ownership marker.
- `models.py` also carries the contract's required members, compiled from the
  OpenAPI `required` lists into `_WIRE_SHAPES`, with `_MODEL_SHAPES` naming the
  component each model is generated from. `from_dict` checks a response
  against them before the model validates, so a required member that is
  absent, or null where the contract does not allow null, is refused at any
  depth. [`types/tests/test_model_contract_parity.py`](types/tests/test_model_contract_parity.py) holds every model to its
  component: members, requiredness, nullability and value kind.
- Run `make regen` from the repository root after an authorized contract or
  generator change. A correct regeneration is deterministic: running it on an
  otherwise clean checkout leaves no diff.

## Handwritten seams

- [`types/ezclassify_contract/_model_helpers.py`](types/ezclassify_contract/_model_helpers.py) is private and limited to
  Pydantic configuration, strict wire decoding, Python-native `from_dict`
  ergonomics, and cross-field source-identity validation. It may support
  generated declarations but must not duplicate their fields.
- [`types/ezclassify_contract/__init__.py`](types/ezclassify_contract/__init__.py) curates the public exports from
  generated wire and domain models; transport behavior belongs in [`client/`](client/).
  A generated model whose name starts with an underscore is a body the client
  decodes but no public method returns, such as the health report; it is
  checked as strictly as the rest and never exported.
- [`client/ezclassify_rest_client/`](client/ezclassify_rest_client/) owns `httpx` transport, wire serialization
  and decoding, the whole-request deadline (`_deadline.py`, a transport whose
  connections hold every network wait to the time left on the request),
  UTF-8/code-point offset conversion, version checks, Context discovery, and
  Context-bound ergonomic facades. Context operation groups send requests to
  the server; they do not evaluate Context behavior locally.
- [`examples/`](examples/) demonstrates public packages. The package test directories,
  [`types/tests/`](types/tests/) and [`client/tests/`](client/tests/), cover their seams; the root [`tests/`](tests/)
  directory replays canonical conformance fixtures.

## Forbidden ownership

- Do not implement parsing, normalization, validation, aggregation, scanning,
  rendering, suggestion, diffing, guide evaluation, access decisions, document
  policy, or any other engine semantics in Python. These operations cross the
  transport boundary to runtime-owned implementations.
- Do not compose schemes, guides, access policies, or Contexts here. The client
  may select and address a published Context and expose its server-resolved
  metadata; composition and evaluation remain upstream.
- Do not hand-copy generated wire fields, maintain a second declaration module,
  or add a fallback model set. Change the contracts and let the spec bot
  propagate them, or change the pinned generator and regenerate the one shipped
  module.
- Do not make generated declarations depend on `client`. The dependency
  direction is adapters to `types`; the repository-root harness remains
  outside the published runtime.
- Do not write [`vendor/spec/`](vendor/spec/) by hand. It is bot-owned: the spec bot, mirroring
  [ezclassify/contracts](https://github.com/ezclassify/contracts), is the only writer, and it is the only one that can stamp
  real provenance.

## Required gates

- Generation ownership and freshness: run `make regen`, then
  `git diff --exit-code -- types/ezclassify_contract/models.py`. Run
  `python -m pytest types/tests/test_generation_boundary.py` in an environment
  with `types[dev]` installed; it enforces the pinned inputs and output, header,
  single public declaration module, and package exports.
- Public API: run `make check-api-surface`. Regenerate [`api-surface.txt`](api-surface.txt) only
  for a deliberate reviewed API change.
- Source quality: run `make typecheck`, `ruff check .`, and
  `ruff format --check .` with the versions pinned in the `Makefile`.
- Behavior and conformance: run `make test`. This covers each package, examples,
  and the root semantic replay suite. In the root suite,
  `test_spec_operation_coverage` requires every OpenAPI operation to be sent by
  a public method and every wire-corpus case to be driven through one, unless
  it is listed with its reason, and `test_required_member_refusal` takes each
  recorded success and refuses it with every required member removed or
  nulled. A live server check additionally runs as
  `make conformance-server URL=<server-url>` when a release candidate endpoint
  is available.
- Distribution: run `make build` and confirm wheels and source distributions
  build for both published packages. CI repeats package and conformance
  tests across the supported Python matrix and requires a clean working tree.
- Review obligation: reject changes that add local engine, policy, or Context
  composition semantics even when tests pass; the absence of those semantics
  is the architectural boundary this repository exists to preserve.
