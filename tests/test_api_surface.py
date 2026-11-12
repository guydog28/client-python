"""Tests for the 1.0 public-surface gate in ``scripts/check_api_surface.py``.

The gate is only as good as the members it can see. Every wire model decodes
through ``from_dict``, which is declared once per shape in the private
``_model_helpers`` module and inherited by the generated ``models.py``. A gate
that resolved private bases within a single module only would leave those
signatures outside the frozen contract, so changing or dropping one would pass
the check in silence. These tests read the surface the gate actually builds.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/check_api_surface.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("_check_api_surface", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def surface(gate) -> str:
    return gate.build_surface()


# The decoder signature _model_helpers declares: the documented entry point
# for decoding a server response into a typed model.
DECODERS = ("def from_dict(cls: type[Self], value: Dict[str, Any]) -> Self",)


def test_members_inherited_from_another_module_reach_the_surface(surface):
    for decoder in DECODERS:
        assert decoder in surface, f"missing inherited decoder: {decoder}"


def test_every_wire_model_publishes_its_decoder(surface):
    import ezclassify_rest_client as contract

    models_block = surface.split("module ezclassify_rest_client.models", 1)[1]
    for name in contract.__all__:
        header = f"  class {name}("
        if header not in models_block:
            continue  # Type aliases declare no class.
        rest = models_block.split(header, 1)[1]
        bases, body = rest.split(")\n", 1)
        if not any(base.strip().startswith("_") for base in bases.split(",")):
            continue  # Enums inherit from str, not from a wire-model base.
        body = body.split("\n  class ", 1)[0]
        assert "def from_dict(" in body, f"{name} publishes no from_dict"


def test_overloads_reach_the_surface_beside_their_implementation(gate):
    # A type-checked caller is held to the overloads, not to the broad
    # implementation signature, so dropping or loosening one is an API
    # change the gate has to see.
    source = (
        "class Reader:\n"
        "    @overload\n"
        "    def read(self, text: str) -> str: ...\n"
        "    @overload\n"
        "    def read(self, *, facts: List[str]) -> str: ...\n"
        "    def read(self, text: str | None = None, *, facts: List[str] | None = None) -> str:\n"
        "        return ''\n"
    )
    lines = gate._format_class(source, gate.ast.parse(source).body[0])
    assert lines == [
        "class Reader",
        "  @overload def read(self, text: str) -> str",
        "  @overload def read(self, *, facts: List[str]) -> str",
        "  def read(self, text: str | None = None, *, facts: List[str] | None = None) -> str",
    ]


def test_the_committed_golden_matches_the_live_surface(surface):
    golden = (REPO_ROOT / "api-surface.txt").read_text(encoding="utf-8")

    assert surface == golden, (
        "api-surface.txt is stale; regenerate it with `make api-surface` and "
        "commit the reviewed diff together with the API change"
    )
