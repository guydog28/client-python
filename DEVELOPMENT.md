# Developing the EzClassify Python SDK

The repo layout, environment setup, the build and test commands, and the
spec-vendoring workflow for working on this repo. For the contribution process
(sign-off, issues, pull requests, commit format), see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

Two PyPI packages plus a repo-root harness that is not published:

| Directory | PyPI name | Purpose |
|---|---|---|
| [`types/`](types/) | `ezclassify-contract` | Pydantic wire and domain contracts |
| [`client/`](client/) | `ezclassify-rest-client` | HTTP client via `httpx` |
| *(repo root)* | `ezclassify` *(not on PyPI)* | Conformance suite + HTTP replayer; delegates to the published packages |

The two publishable packages are version-bumped in lockstep; [`client/`](client/)
depends on [`types/`](types/), so editable installs go in that order.

## Local development

Python 3.11+. Work inside a virtual environment so the editable installs do not
touch system packages:

```sh
python3 -m venv .venv && source .venv/bin/activate
make test   # creates .venv, installs test dependencies, and runs every suite
```

| Action | Command | Notes |
|--------|---------|-------|
| Install for development | `pip install -e types/ -e client/` | Editable installs in dependency order. |
| Generate API reference | `make docs` | Requires editable local packages installed in `.venv`; open `dist/api/ezclassify_rest_client.html` and `dist/api/ezclassify_contract.html`. |
| Test | `make test` | Runs contract, client, example, and root conformance suites; `make test-verbose` adds detailed output. |
| Lint + format check | `make lint` | `ruff check .` and `ruff format --check .` at the pinned version CI uses (CI runs this target). `ruff format .` applies the formatting. |
| Type check | `make typecheck` | `mypy --strict` over the two `py.typed` packages (config in the root [`pyproject.toml`](pyproject.toml) `[tool.mypy]`); the Makefile pins the mypy version CI uses. |
| Conformance only | `pip install -e types/ -e client/ -e ".[dev]" && pytest tests/test_conformance.py` | Self-contained HTTP replayer; no server needed. |
| Build distributions (wheel + sdist) | `python3 -m build client/` | or `make build` (builds both publishable packages into `dist/`). The build backend is `hatchling`; install the front-end once with `pip install build`. |
| Regenerate models | `make regen` | See "Spec and conformance" below. [`vendor/spec/`](vendor/spec/) itself is bot-owned; you cannot refresh it from here. |
| Clean | `make clean` (`make distclean` also drops the virtualenvs) | |

Lint and formatting are enforced with [ruff](https://docs.astral.sh/ruff/).
The full local gate, the same checks CI runs, is:

```sh
make lint test typecheck check-api-surface
```

The conformance and unit suites are the functional gate. The public API of the
published packages is frozen at 1.0 in [`api-surface.txt`](api-surface.txt); `make check-api-surface`
is the CI gate, and `make api-surface` regenerates it for a deliberate,
reviewed API change committed alongside that change.

## Spec and conformance

- **The spec is vendored, not authored here.** The Pydantic models in
  `ezclassify-contract` track the OpenAPI spec under [`vendor/spec/`](vendor/spec/). That
  mirror is written exclusively by the EzClassify spec bot from
  [ezclassify/contracts](https://github.com/ezclassify/contracts), landing as `ezclassify-spec-bot`;
  `vendor-readonly.yml` rejects a [`vendor/spec/`](vendor/spec/) commit from anyone else. There
  is no local target that refreshes it.
  `make regen` writes the shipped `models.py` directly from both the OpenAPI
  components and canonical JSON Schemas. CI regenerates that production file
  and fails on any diff. Python-only parsing ergonomics and cross-field checks
  live separately in the private `_model_helpers.py` module.
  Wrapper-only changes don't touch [`vendor/`](vendor/). Spec changes belong upstream in
  [ezclassify/contracts](https://github.com/ezclassify/contracts); report them through the [central product tracker](https://github.com/ezclassify/ezclassify/issues/new/choose).
- **Conformance plans define parity.** The client is conformance-tested against
  the same vectors as the TypeScript engine, through a self-contained HTTP
  replayer (no server needed):

  ```sh
  pip install -e types/ -e client/ -e ".[dev]"   # packages + harness test dependencies
  pytest tests/test_conformance.py
  ```

  A change that breaks a conformance plan needs the plan changed in the [ezclassify/contracts](https://github.com/ezclassify/contracts) repository first.

  Live deployment acceptance is a separate lane: run `make smoke URL=<server-url>`
  against a licensed, content-configured REST deployment. Missing prerequisites
  fail that lane; the standalone tests use the committed public recordings.

## What to Know Before Changing Things

- **Engine behavior belongs to EzClassify Runtime.** This SDK handles HTTP
  transport and decoding. Report suspected evaluation defects through the
  [central product tracker](https://github.com/ezclassify/ezclassify/issues/new/choose),
  with a synthetic marking, the scheme and Context versions, and sanitized
  request/response details. Runtime source access is not required.

## Source reference

`make docs` uses Python's standard-library `pydoc` to write HTML for every
module in the two published packages, including the generated contract models
and private support modules. It imports the local editable packages, so install
them with `.venv/bin/pip install -e types -e client` first. Generation makes no
REST requests. The output stays under ignored `dist/api/`; examples, repository
scripts and the unpublished conformance harness are outside this package API.
Pydoc displays docstrings as plain text, including Sphinx role notation. Its
stdlib and third-party module links are not bundled; use
`.venv/bin/python -m pydoc -b` for interactive navigation to installed dependency
documentation. Generated pages include local source paths and are local references.

Read the client package for Context operations, credentials, caching and errors;
read the contract package for the generated request, response and domain models.
The generated model declarations remain owned by `make regen`.

For the unpublished HTTP replayer and maintenance-script functions, run
`make docs-source` and open `dist/api/ezclassify.html` and the script-name HTML
files beside it. This additionally
requires PyYAML, already installed by `make test` or the regeneration environment.
The scripts' `__main__` guards prevent documentation imports from regenerating
models, notices or API goldens. Test modules are excluded. The Node generator
entrypoint and shell live-conformance driver are not imported: their native
commands are `make regen` and `make conformance-server URL=...`, respectively.
The runnable example keeps its CLI contract in
[examples/llm-classify/README.md](examples/llm-classify/README.md).
