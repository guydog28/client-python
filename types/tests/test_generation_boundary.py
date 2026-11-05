"""Tests for the production model generation boundary."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import re
from pathlib import Path

from typing import Any

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from typing_extensions import Annotated

import ezclassify_contract
from ezclassify_contract import _model_helpers, models

REPO_ROOT = Path(__file__).resolve().parents[2]


def _provenance_row(field: str) -> str | None:
    """Read one row out of the two-column provenance table in vendor/SPEC.md.

    The writer emits the table with the label in backticks (``contracts@``) or
    bare (``contractsPackages``), so both are accepted. Returns the value cell
    stripped of whitespace and backticks, or ``None`` when the row is absent.
    """
    text = (REPO_ROOT / "vendor/SPEC.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^\|\s*`?{re.escape(field)}`?\s*\|([^|]*)\|", text, re.MULTILINE
    )
    if match is None:
        return None
    return match.group(1).replace("`", "").strip()


def _generated_model_names() -> list[str]:
    tree = ast.parse((REPO_ROOT / "scripts/gen_models.py").read_text())
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MODEL_ORDER"
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            assert isinstance(value, list)
            return value
    raise AssertionError("MODEL_ORDER is missing from the production generator")


def test_only_the_shipped_model_module_holds_generated_declarations() -> None:
    model_names = set(_generated_model_names())
    package_dir = REPO_ROOT / "types/ezclassify_contract"
    declarations: dict[str, set[str]] = {}

    for module_path in package_dir.glob("*.py"):
        if module_path.name.startswith("_"):
            continue
        tree = ast.parse(module_path.read_text())
        declared_models = {
            statement.name
            for statement in tree.body
            if isinstance(statement, ast.ClassDef) and statement.name in model_names
        }
        if declared_models:
            declarations[module_path.name] = declared_models

    assert declarations == {"models.py": model_names}


def test_launcher_pins_the_complete_generator_implementation() -> None:
    generator = REPO_ROOT / "scripts/gen_models.py"
    launcher = REPO_ROOT / "scripts/gen.mjs"
    generator_hash = hashlib.sha256(generator.read_bytes()).hexdigest()
    launcher_source = launcher.read_text()

    assert f"expectedGeneratorHash = '{generator_hash}'" in launcher_source


def test_bot_manifest_pins_every_generator_input_and_shipped_output() -> None:
    manifest = json.loads((REPO_ROOT / "vendor/spec/MANIFEST.json").read_text())
    generator = manifest["generators"]["python"]

    assert (
        generator["sha256"]
        == hashlib.sha256((REPO_ROOT / generator["script"]).read_bytes()).hexdigest()
    )
    assert generator["additionalInputs"] == [
        {
            "path": "scripts/gen_models.py",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "scripts/gen_models.py").read_bytes()
            ).hexdigest(),
        },
        {
            "path": "tools/requirements-regen.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "tools/requirements-regen.txt").read_bytes()
            ).hexdigest(),
        },
    ]
    assert manifest["generatedPaths"] == ["types/ezclassify_contract/models.py"]


def _generator() -> object:
    """Load scripts/gen_models.py and point it at the vendored contract.

    The generator is a script, not an installed module, so it is loaded by
    path. It imports PyYAML, which the [dev] extra declares for exactly this
    reason; a missing parser has to fail here, not skip.
    """
    spec = importlib.util.spec_from_file_location(
        "ezclassify_gen_models", REPO_ROOT / "scripts/gen_models.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_public_model_resolves_against_the_vendored_contract() -> None:
    """The generator's configuration and the vendored contract still agree.

    Resolving every model here, rather than during ``make regen`` one model at
    a time, means a re-vendor that drops or reshapes a schema fails in the
    suite, naming every affected model and the table that decides it, before
    anyone tries to regenerate.
    """
    module = _generator()
    generator = module.Generator(REPO_ROOT / "vendor/spec")  # type: ignore[attr-defined]

    unresolved = generator.unresolved_sources()
    stale = generator.stale_overrides()

    assert generator.public, "the generator inspected no models"
    assert not unresolved, "\n".join(
        ["public models with no schema source:", *unresolved]
    )
    assert not stale, "\n".join(["generator config that matches no schema:", *stale])


def test_oas31_null_unions_preserve_concrete_public_types() -> None:
    """Required null fields must retain their non-null model and scalar types."""
    generator = _generator().Generator(REPO_ROOT / "vendor/spec")

    cases = [
        ("DocumentAuditReport", "whole", "Optional[str]"),
        ("DocumentAuditReport", "wholeValidation", "Optional[MarkingValidation]"),
    ]
    for owner, prop, expected in cases:
        schema = generator.source(owner)["properties"][prop]
        assert generator.type_for(schema, owner, prop) == expected

    assert (
        generator.type_for(
            {"oneOf": [{"type": "string"}, {"type": "null"}]}, "Probe", "value"
        )
        == "Optional[str]"
    )
    assert (
        generator.type_for({"type": ["string", "number"]}, "Probe", "value")
        == "Union[str, float]"
    )
    assert (
        generator.type_for({"type": ["string", "null"]}, "Probe", "value")
        == "Optional[str]"
    )
    assert generator.type_for({"type": "null"}, "Probe", "value") == "None"

    assert models.DocumentAuditReport.__annotations__["whole"] == "Optional[str]"

    common = {
        "whole": None,
        "wholes": [],
        "wholeValidation": None,
        "parts": [],
        "wholeCoversParts": None,
        "unmarkedSpans": [],
        "proceduralFlags": [],
        "overallVerdict": "pass",
        "vocabulary": None,
        "documentDigest": "sha256:document",
        "markingRequirements": {"whole": False, "part": False},
        "guideAssessment": None,
        "limitations": [],
    }
    assert models.DocumentAuditReport.model_validate(common).whole is None
    with pytest.raises(PydanticValidationError):
        models.DocumentAuditReport.model_validate({**common, "whole": {}})


def _declares_enum(generator: Any, schema: dict[str, Any]) -> bool:
    """Whether a property schema holds an ``enum`` at any value position.

    Follows references, list items, map values and union arms, and stops at
    a nested object's own properties, which belong to that object's model.
    A ``const`` is not an enum: it is a fixed protocol value, not a set a
    server can grow.
    """
    schema = generator.resolve_schema_ref(schema)
    if schema.get("enum"):
        return True
    arms: list[Any] = list(schema.get("anyOf") or schema.get("oneOf") or [])
    arms += list(schema.get("allOf") or [])
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            arms.append(schema[key])
    return any(_declares_enum(generator, arm) for arm in arms)


def _shaped_unknown(generator: Any, schema: dict[str, Any]) -> Any:
    """The unknown enum value, nested where the property holds its enum.

    A property can hold its enum directly, as list items or as map values. A
    bare string sent to a list of roles is refused for not being a list, which
    says nothing about the enum, so the probe goes where the enum is.
    """
    schema = generator.resolve_schema_ref(schema)
    if schema.get("enum"):
        return _UNKNOWN
    if isinstance(schema.get("items"), dict):
        return [_shaped_unknown(generator, schema["items"])]
    if isinstance(schema.get("additionalProperties"), dict):
        return {"key": _shaped_unknown(generator, schema["additionalProperties"])}
    arms: list[Any] = list(schema.get("anyOf") or schema.get("oneOf") or [])
    arms += list(schema.get("allOf") or [])
    for arm in arms:
        if _declares_enum(generator, arm):
            return _shaped_unknown(generator, arm)
    return _UNKNOWN


def _enum_positions() -> list[tuple[str, str, bool, bool, Any]]:
    """Every enum position of every generated model, from the contract alone.

    Each entry is (model, wire property, in a request, in a response, the
    unknown value shaped for that property).
    """
    module: Any = _generator()
    generator = module.Generator(REPO_ROOT / "vendor/spec")
    positions = []
    for name in module.MODEL_ORDER:
        if name == "Confidence":
            continue
        schema = generator.merge_object_union(generator.source(name))
        for wire, prop in schema.get("properties", {}).items():
            override = module.TYPE_OVERRIDES.get((name, wire))
            if isinstance(override, module.EnumOverride) or (
                override is None and _declares_enum(generator, prop)
            ):
                positions.append(
                    (
                        name,
                        wire,
                        *generator.directions(name),
                        _shaped_unknown(generator, prop),
                    )
                )
    return positions


def _field_adapter(model: str, wire: str) -> TypeAdapter[Any]:
    fields = getattr(models, model).model_fields
    field = next(f for n, f in fields.items() if wire in (n, f.alias))
    annotation = field.annotation
    if field.metadata:
        annotation = Annotated[(annotation, *field.metadata)]  # type: ignore[valid-type]
    return TypeAdapter(annotation)


_UNKNOWN = "value-added-by-a-newer-server"


def test_every_response_enum_position_decodes_an_unknown_value() -> None:
    """Open-response, closed-request, checked at every enum the contract has.

    Found from the vendored schemas rather than from the generated code, so a
    new enum position is covered the day it is vendored. A position on a
    model that ever comes back in a response keeps an unknown string on
    decode. A position on a model that only travels in requests refuses it.
    """
    positions = _enum_positions()
    response = [p for p in positions if p[3]]
    request_only = [p for p in positions if p[2] and not p[3]]
    assert response and request_only, "the contract must exercise both sides"

    for model, wire, _, _, probe in response:
        assert _field_adapter(model, wire).validate_python(probe) == probe, (
            f"{model}.{wire} refuses an enum value a newer server could send"
        )
    for model, wire, _, _, probe in request_only:
        with pytest.raises(PydanticValidationError):
            _field_adapter(model, wire).validate_python(probe)


def test_every_enum_position_used_both_ways_refuses_an_unknown_value_on_construction() -> (
    None
):
    """A model callers also send refuses an undeclared value when they build it."""
    both = [p for p in _enum_positions() if p[2] and p[3]]
    assert both, "the contract must have an enum on a model used both ways"

    token = _model_helpers._CONSTRUCTING.set(True)
    try:
        for model, wire, _, _, probe in both:
            with pytest.raises(PydanticValidationError) as failure:
                _field_adapter(model, wire).validate_python(probe)
            assert failure.value.errors()[0]["type"] == "literal_error", (model, wire)
    finally:
        _model_helpers._CONSTRUCTING.reset(token)


def test_a_dropped_schema_names_the_model_and_the_table() -> None:
    """The preflight has to be worth having: prove it fires and says enough.

    Drops the component ``StructuralView`` and ``StructuralViewCategory`` are
    both sourced from, in a copy of the vendored contract, and checks the
    failure names both models and both tables. Without this, the preflight
    could silently stop resolving anything and still look green.
    """
    module = _generator()
    generator = module.Generator(REPO_ROOT / "vendor/spec")  # type: ignore[attr-defined]
    del generator.components["SchemeViewResponse"]

    with pytest.raises(module.MissingSchemaSource) as failure:  # type: ignore[attr-defined]
        generator.preflight()

    message = str(failure.value)
    assert "StructuralView:" in message
    assert "StructuralViewCategory:" in message
    assert "COMPONENT_SOURCES" in message
    assert "INLINE_SOURCES" in message


def test_a_subclass_must_declare_what_it_inherits_exactly_as_its_base_does() -> None:
    """ProcessResult inherits ValidateResult's fields instead of declaring them.

    That is only sound while ProcessResult's own schema says the same thing
    about each of them. Change one shared field's type, and drop another from
    ProcessResult's schema, in a copy of the contract: the preflight has to
    name both rather than let the subclass silently inherit the base's shape.
    """
    module = _generator()
    generator = module.Generator(REPO_ROOT / "vendor/spec")  # type: ignore[attr-defined]
    own = generator.source("ProcessResult")["properties"]
    own["rendered"] = {"type": "integer"}
    del own["displayColor"]

    with pytest.raises(module.MissingSchemaSource) as failure:  # type: ignore[attr-defined]
        generator.preflight()

    message = str(failure.value)
    assert "BASE_MODELS['ProcessResult']" in message
    assert "`rendered: int` but inherits `rendered: str` from ValidateResult" in message
    assert "no 'displayColor' property" in message


def test_generated_docstrings_keep_the_contracts_paragraphs_and_lists() -> None:
    """A described list stays a list in ``help()``, one item to a line."""
    doc = inspect.getdoc(models.ProcessResult) or ""
    assert "\n\nProcess is the author's call." in doc
    assert (
        "\n- the corrections that turn the text into canonical text, inside "
        "`recognition`;\n- what was read before repair" in doc
    )
    assert " - what was read" not in doc


def test_manifest_records_real_upstream_provenance() -> None:
    """The manifest names the upstream contract commit and package versions."""
    manifest = json.loads((REPO_ROOT / "vendor/spec/MANIFEST.json").read_text())

    assert re.fullmatch(r"[0-9a-f]{40}", manifest["contractsSha"]), (
        f"contractsSha is {manifest['contractsSha']!r}, not a real commit SHA. "
        "A hand-refreshed manifest is for local iteration only. Take the real "
        "bump from the spec bot."
    )
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["specDigest"]), (
        f"specDigest is {manifest['specDigest']!r}, not a bundle digest."
    )

    packages = manifest["sourcePackages"]
    assert packages, "sourcePackages must name the upstream packages"
    for name, version in packages.items():
        assert name.startswith("@ezclassify/"), (
            f"sourcePackages names {name!r}, which is not a contracts package."
        )
        assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", version), (
            f"sourcePackages[{name!r}] is {version!r}, not a real version. "
            "A hand re-vendor leaves a placeholder here; only the spec bot "
            "knows the published versions."
        )


def test_spec_markdown_agrees_with_the_manifest_about_provenance() -> None:
    """Two files, one fact: they must agree.

    ``vendor/SPEC.md`` and ``vendor/spec/MANIFEST.json`` are written in the same
    pass by the spec bot and record the same upstream commit twice. Without
    this comparison, a ``contractsSha`` rewritten in the manifest alone would
    leave the suite fully green.

    The assertions are about internal consistency, never a blessed commit: the
    bundle is bot-owned and re-vendored on its own cadence, so a literal SHA
    here would go red on the next legitimate bump and could only be repaired by
    a human the bot cannot summon.
    """
    manifest = json.loads((REPO_ROOT / "vendor/spec/MANIFEST.json").read_text())

    recorded_sha = _provenance_row("contracts@")
    assert recorded_sha is not None, (
        "vendor/SPEC.md has no `contracts@` provenance row. The spec is owned "
        "by ezclassify/contracts; a bundle that cannot name its source commit "
        "in the document a reviewer reads is not reviewable."
    )
    assert recorded_sha == manifest["contractsSha"], (
        "vendor/SPEC.md and vendor/spec/MANIFEST.json disagree about the "
        "upstream commit, so at least one of them is lying about what was "
        "vendored. Refresh through the spec bot rather than editing either by "
        "hand.\n"
        f"  SPEC.md  contracts@:   {recorded_sha}\n"
        f"  MANIFEST contractsSha: {manifest['contractsSha']}"
    )

    source_url = _provenance_row("specSourceUrl")
    assert source_url is not None, "vendor/SPEC.md has no `specSourceUrl` row"
    assert "github.com/ezclassify/contracts" in source_url, (
        f"specSourceUrl does not point at the contracts repo: {source_url}"
    )
    assert manifest["contractsSha"] in source_url, (
        "specSourceUrl points at a different commit than the one the manifest "
        f"records.\n  url:          {source_url}\n"
        f"  contractsSha: {manifest['contractsSha']}"
    )

    listed = _provenance_row("contractsPackages")
    assert listed is not None, "vendor/SPEC.md has no `contractsPackages` row"
    assert {entry.strip() for entry in listed.split(",")} == {
        f"{name}@{version}" for name, version in manifest["sourcePackages"].items()
    }, (
        "vendor/SPEC.md's contractsPackages row and MANIFEST.json's "
        "sourcePackages describe different upstream packages.\n"
        f"  SPEC.md:  {listed}\n"
        f"  MANIFEST: {manifest['sourcePackages']}"
    )


def test_manifest_openapi_hash_matches_the_vendored_bytes() -> None:
    """Pins the manifest to the file it describes.

    CI verifies this too, but only on the hosted runner. Keeping it in the suite
    means a bad vendor drop fails on the machine that made it.
    """
    manifest = json.loads((REPO_ROOT / "vendor/spec/MANIFEST.json").read_text())
    actual = hashlib.sha256((REPO_ROOT / "vendor/spec/openapi.yaml").read_bytes())

    assert manifest["openapiSha256"] == actual.hexdigest()


def _vendored_contract_digest() -> str:
    """Recompute the digest gen_models.py stamps into the models.py header.

    Must stay byte-identical to the ``generate()`` implementation in
    scripts/gen_models.py: sha256 over openapi.yaml followed by every
    ``*.schema.json`` in sorted order.
    """
    spec_dir = REPO_ROOT / "vendor/spec"
    digest = hashlib.sha256()
    for path in [
        spec_dir / "openapi.yaml",
        *sorted((spec_dir / "json-schemas").glob("*.schema.json")),
    ]:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_shipped_models_are_marked_generated() -> None:
    """The header must pin the contracts actually vendored, not just look like it.

    Asserting only the prefix would let a re-vendor land while models.py kept
    the previous digest, with the marker well-formed and the claim false. The
    digest is compared for real here so a forgotten `make regen` fails loudly.
    """
    first_line = (
        (REPO_ROOT / "types/ezclassify_contract/models.py").read_text().splitlines()[0]
    )

    expected = f"# Code generated from vendored contracts@{_vendored_contract_digest()}. DO NOT EDIT."
    assert first_line == expected, (
        "models.py was generated from different contract bytes than the ones now "
        "in vendor/spec/. Normally the fix is `make regen`.\n"
        "If regen itself fails, the vendored contract dropped or reshaped a schema "
        "the generator still expects, and the repair belongs upstream in "
        "ezclassify/contracts, not in a hand-edit here.\n"
        f"  header:   {first_line}\n"
        f"  expected: {expected}"
    )


@pytest.mark.parametrize("model_name", _generated_model_names())
def test_each_generated_model_is_the_exported_production_type(model_name: str) -> None:
    """Prevent a second handwritten declaration from shadowing generated output.

    A private model is a body the client decodes but no public method
    returns, so the package does not export it.
    """
    generated = getattr(models, model_name)

    if model_name.startswith("_"):
        assert model_name not in ezclassify_contract.__all__
        assert not hasattr(ezclassify_contract, model_name)
    else:
        assert getattr(ezclassify_contract, model_name) is generated
    assert generated.__module__ == "ezclassify_contract.models"
