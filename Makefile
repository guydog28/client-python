.PHONY: regen test test-verbose build lint typecheck clean distclean conformance-server api-surface check-api-surface notices docs docs-source

PYTHON ?= python3
VENV := .venv
REGEN_VENV := .regen-venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

# There is deliberately no local re-vendor target. vendor/spec/ is bot-owned:
# the bundle is mirrored out of ezclassify/contracts by the spec bot and lands
# as ezclassify-spec-bot. .github/workflows/vendor-readonly.yml rejects a
# vendor/spec/ commit from any other identity, and
# types/tests/test_generation_boundary.py rejects a manifest without real
# upstream provenance. To advance the spec, update contracts and let the spec
# bot propagate it, then run `make regen`.
regen:
	$(PYTHON) -m venv "$(REGEN_VENV)"
	$(REGEN_VENV)/bin/pip install -q -r tools/requirements-regen.txt
	REGEN_PYTHON=$(REGEN_VENV)/bin/python node scripts/gen.mjs vendor/spec
	@echo "Regenerated shipped types/ezclassify_contract/models.py"

# build: build sdist + wheel artifacts for the two published packages into
#   dist/ (gitignored).
build:
	rm -rf dist
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -q build
	$(VENV)/bin/python -m build --outdir dist types
	$(VENV)/bin/python -m build --outdir dist client

# The public API of the published packages is frozen at 1.0; api-surface.txt
# is the reviewed contract. Regenerate it only for a deliberate, reviewed API
# change and commit it together with that change. Stdlib-only, no venv needed.
api-surface:
	$(PYTHON) scripts/check_api_surface.py --write

check-api-surface:
	$(PYTHON) scripts/check_api_surface.py --check

# Regenerate THIRD-PARTY-NOTICES.md from the published packages' declared
# runtime dependencies. CI regenerates and diffs it, so commit the result.
notices:
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -e types -e client -q
	$(VENV)/bin/python scripts/gen-notices.py

# lint: ruff lint rules plus the format check, exactly as CI runs them (CI
#   calls this target, so the pin below is the only one). `ruff format .`
#   fixes what the check reports.
RUFF_VERSION := 0.17.1

lint:
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -q ruff==$(RUFF_VERSION)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

# typecheck: mypy --strict over the two published, py.typed packages
#   (config in the root pyproject.toml [tool.mypy] table). CI runs the same
#   gate in the checks job; the version pin here matches it.
typecheck:
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -e types -e client -q
	$(PIP) install -q mypy==2.4.0
	$(VENV)/bin/mypy

test:
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -e "types[dev]" -q
	cd types && ../$(PYTEST)
	$(PIP) install -e types -e "client[dev]" -q
	cd client && ../$(PYTEST)
	cd examples/llm-classify && ../../$(PYTEST) tests/
	$(PIP) install -e types -e client -e ".[dev]" -q
	$(PYTEST) tests/

test-verbose:
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install -e "types[dev]" -q
	cd types && ../$(PYTEST) -v -s -p no:xdist --tb=long
	$(PIP) install -e types -e "client[dev]" -q
	cd client && ../$(PYTEST) -v -s -p no:xdist --tb=long
	cd examples/llm-classify && ../../$(PYTEST) tests/ -v -s -p no:xdist --tb=long
	$(PIP) install -e types -e client -e ".[dev]" -q
	$(PYTEST) tests/ -v -s -p no:xdist --tb=long

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache \) -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

distclean: clean
	rm -rf $(VENV) $(REGEN_VENV)

conformance-server: test-conformance-runner
	EZC_SMOKE_URL=$(URL) bash scripts/conformance-server.sh

# Live lanes require caller-provided, licensed and content-configured runtimes.
.PHONY: smoke test-mcp-live
smoke:
	EZC_SMOKE_URL=$(URL) $(PYTEST) tests/live/test_smoke.py

test-mcp-live:
	cd examples/llm-classify && ../../$(PYTEST) tests/live/test_e2e.py

# Pure helper tests for the explicit Python-backed live conformance lane.
.PHONY: test-conformance-runner
test-conformance-runner:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p test_conformance_server.py

# Stdlib pydoc imports the editable local packages without making API requests.
# Install them first with .venv/bin/pip install -e types -e client.
docs:
	rm -rf dist/api
	mkdir -p dist/api
	cd dist/api && PYTHONPATH="$(CURDIR)/client:$(CURDIR)/types" ../../$(VENV)/bin/python -c 'import ezclassify_rest_client, ezclassify_contract, pydoc; pydoc.writedoc("ezclassify_rest_client"); pydoc.writedocs("../../client/ezclassify_rest_client", "ezclassify_rest_client."); pydoc.writedoc("ezclassify_contract"); pydoc.writedocs("../../types/ezclassify_contract", "ezclassify_contract.")'

# Maintenance scripts guard execution with __main__; importing them for pydoc
# does not regenerate models, notices, or API goldens.
docs-source: docs
	cd dist/api && PYTHONPATH="$(CURDIR):$(CURDIR)/client:$(CURDIR)/types" ../../$(VENV)/bin/python -c 'import pydoc; pydoc.writedoc("ezclassify"); pydoc.writedocs("../../ezclassify", "ezclassify."); pydoc.writedoc(pydoc.importfile("../../scripts/check_api_surface.py")); pydoc.writedoc(pydoc.importfile("../../scripts/gen_models.py")); pydoc.writedoc(pydoc.importfile("../../scripts/gen-notices.py"))'
