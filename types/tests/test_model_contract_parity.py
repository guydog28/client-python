"""Every generated model says what its OpenAPI component says.

A model generated from a component has to agree with it member by member:
the same members, a value that may be null exactly where the contract allows
null, a default only where the contract lets the member be absent (or, on a
model a request carries, where a caller building one may leave it out), and
the same kind of value (string, number, boolean, array or object). The generator writes the models from the
contract, but its override tables can say otherwise, and this is where an
override that has drifted from the contract is caught.

Open positions the generator types as ``Any`` or a union are not compared by
kind; their required members are still checked on decode by ``from_dict``.
"""

from __future__ import annotations

import types
import typing
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import yaml
from pydantic import BaseModel, StrictBool
from pydantic.fields import FieldInfo

from ezclassify_contract import models

SPEC = Path(__file__).resolve().parents[2] / "vendor/spec/openapi.yaml"
DOCUMENT: Dict[str, Any] = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
COMPONENTS: Dict[str, Any] = DOCUMENT["components"]["schemas"]


def _request_components() -> set[str]:
    """Every schema component a request body can carry."""
    found: set[str] = set()
    pending: list[Any] = [
        operation["requestBody"]
        for item in DOCUMENT["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict) and "requestBody" in operation
    ]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in found:
                    found.add(name)
                    pending.append(COMPONENTS[name])
            pending.extend(node.values())
    return found


# A caller builds these with keywords to put in a request, so a required
# member may carry a default for that; decoding still refuses its absence.
REQUEST_COMPONENTS = _request_components()


def _target(schema: Any) -> Any:
    while isinstance(schema, dict) and "$ref" in schema:
        schema = COMPONENTS[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _allows_null(schema: Any) -> bool:
    schema = _target(schema)
    if not isinstance(schema, dict) or not schema:
        return True
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if alternatives:
        return any(_allows_null(item) for item in alternatives)
    return False


def _wire_kind(schema: Any) -> Optional[str]:
    """The JSON kind a schema position holds, or ``None`` when it is mixed."""
    schema = _target(schema)
    if not isinstance(schema, dict):
        return None
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if alternatives:
        kinds = {
            _wire_kind(item)
            for item in alternatives
            if _target(item).get("type") != "null"
        }
        return kinds.pop() if len(kinds) == 1 else None
    kind = schema.get("type")
    if isinstance(kind, list):
        concrete = [k for k in kind if k != "null"]
        kind = concrete[0] if len(concrete) == 1 else None
    if kind is None and "properties" in schema:
        kind = "object"
    if kind is None and "const" in schema:
        kind = type(schema["const"]).__name__
    return (
        {
            "string": "string",
            "str": "string",
            "integer": "number",
            "number": "number",
            "boolean": "boolean",
            "bool": "boolean",
            "array": "array",
            "object": "object",
        }.get(kind)
        if isinstance(kind, str)
        else None
    )


def _strip(annotation: Any) -> tuple[Any, bool]:
    """Remove ``Optional`` and ``Annotated``; say whether ``None`` was allowed."""
    nullable = False
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
            continue
        if origin in (typing.Union, types.UnionType):
            arms = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(arms) < len(typing.get_args(annotation)):
                nullable = True
            if len(arms) == 1:
                annotation = arms[0]
                continue
        return annotation, nullable


def _python_kind(annotation: Any) -> Optional[str]:
    annotation, _ = _strip(annotation)
    origin = typing.get_origin(annotation)
    if origin in (list, typing.List):
        return "array"
    if origin in (dict, typing.Dict):
        return "object"
    if origin is typing.Literal:
        values = {type(v).__name__ for v in typing.get_args(annotation)}
        return {"str": "string", "int": "number", "bool": "boolean"}.get(
            values.pop() if len(values) == 1 else ""
        )
    if annotation is StrictBool or annotation is bool:
        return "boolean"
    if annotation in (int, float):
        return "number"
    if annotation is str:
        return "string"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "object"
    if isinstance(annotation, type) and issubclass(annotation, str):
        return "string"  # a str-valued Enum
    return None  # Any, or a union of kinds: not compared


def _field(model: type[BaseModel], wire: str) -> Optional[FieldInfo]:
    for name, field in model.model_fields.items():
        if (field.alias or name) == wire:
            return field
    return None


PAIRS = sorted(models._MODEL_SHAPES.items())


@pytest.mark.parametrize(("model_name", "component"), PAIRS, ids=[p[0] for p in PAIRS])
def test_model_agrees_with_its_component(model_name: str, component: str) -> None:
    model = getattr(models, model_name)
    schema = _target(COMPONENTS[component])
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if alternatives:
        # A union the generator folds into one model: a member is required
        # only when every alternative requires it.
        variants = [_target(item) for item in alternatives]
        properties: Dict[str, Any] = {}
        for variant in variants:
            properties.update(variant.get("properties", {}))
        required = set.intersection(*(set(v.get("required", [])) for v in variants))
    else:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

    problems: list[str] = []
    for wire, member in properties.items():
        field = _field(model, wire)
        if field is None:
            problems.append(f"{wire}: the contract declares it, the model does not")
            continue
        _, python_nullable = _strip(field.annotation)
        if wire in required:
            if not field.is_required() and component not in REQUEST_COMPONENTS:
                problems.append(
                    f"{wire}: required in the contract, defaulted in a model only "
                    "responses carry"
                )
            if _allows_null(member) and not python_nullable:
                problems.append(f"{wire}: the contract allows null, the model does not")
            if not _allows_null(member) and python_nullable:
                problems.append(
                    f"{wire}: required and never null in the contract, Optional "
                    "in the model"
                )
        elif field.is_required():
            problems.append(f"{wire}: optional in the contract, required in the model")
        wire_kind = _wire_kind(member)
        python_kind = _python_kind(field.annotation)
        if wire_kind and python_kind and wire_kind != python_kind:
            problems.append(
                f"{wire}: the contract holds {wire_kind}, the model {python_kind}"
            )
    undeclared = sorted(
        (field.alias or name)
        for name, field in model.model_fields.items()
        if (field.alias or name) not in properties
    )
    if undeclared:
        problems.append(
            f"the model declares members the contract does not: {undeclared}"
        )
    assert not problems, f"{model_name} vs {component}:\n  " + "\n  ".join(problems)


# Public models generated from no OpenAPI component of their own: inline
# objects and JSON Schema enums. The component around each one covers it.
NO_COMPONENT = {
    "AuditPart",
    "AuditWhole",
    "Confidence",
    "FilterCount",
    "StructuralViewCategory",
}


def test_every_public_model_is_compared_or_has_no_component() -> None:
    import ezclassify_contract

    exported = {
        name
        for name in ezclassify_contract.__all__
        if isinstance(getattr(models, name, None), type)
    }
    compared = {name for name, _ in PAIRS}
    assert exported - compared == NO_COMPONENT
