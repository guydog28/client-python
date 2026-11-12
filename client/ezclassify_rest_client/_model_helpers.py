"""Handwritten behavior shared by generated wire-model declarations.

The wire fields live exclusively in :mod:`ezclassify_rest_client.models`,
which is generated from the vendored schemas and OpenAPI document.  This
module is intentionally limited to Python ergonomics and cross-field checks
that JSON Schema cannot express as a single class declaration.
"""

from __future__ import annotations

from contextvars import ContextVar
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import (
    CoreSchema,
    InitErrorDetails,
    PydanticCustomError,
    PydanticKnownError,
    core_schema,
)
from pydantic_core import ValidationError as _PydanticValidationError
from typing_extensions import Self

if TYPE_CHECKING:
    from .models import ContextComponent

# True while a caller is building a model with keywords, including every model
# nested inside it that is built from a plain value. Decoding (model_validate,
# from_dict, nested decode) never sets it. See _KnownOnConstruction.
_CONSTRUCTING: ContextVar[bool] = ContextVar("_ezclassify_constructing", default=False)


class _WireModel(BaseModel):
    """Base behavior for generated Pydantic wire models."""

    model_config = ConfigDict(populate_by_name=True)

    def __init__(self, /, **data: Any) -> None:
        # Keyword construction is how a caller builds a request, so it is the
        # one path that refuses an enum value the contract does not declare.
        # The flag is scoped to this call and every nested model it validates.
        token = _CONSTRUCTING.set(True)
        try:
            super().__init__(**data)
        finally:
            _CONSTRUCTING.reset(token)

    # Keeps model_validate, from_dict and nested decoding on the core validator
    # instead of routing them through this __init__; see _ClosedOnConstruction.
    __init__.__pydantic_base_init__ = True  # type: ignore[attr-defined]

    @classmethod
    def from_dict(cls: type[Self], value: Dict[str, Any]) -> Self:
        """Decode a raw wire dictionary as this model, strictly.

        This is the decoder for a body read off the wire. Before the model
        validates, every member the contract requires is checked at every
        depth, including inside the members this package keeps as open
        dictionaries: a required member that is absent, or null where the
        contract does not allow null, is refused. A default a model declares
        for a required member is for building one with keywords, and decoding
        never fills it in. ``model_validate`` remains Pydantic's structural
        validation and does not run this check.

        Raises:
            pydantic.ValidationError: The value is not this model. For a
                required member, the error's ``loc`` locates it from the
                value's root, as member names and array indices.
        """
        _check_wire_shape(cls.__name__, value)
        return cls.model_validate(value)


class _ClosedOnConstruction(_WireModel):
    """A wire model that travels in requests as well as responses.

    Decoding stays open like every response model, so a field a newer server
    adds is ignored. Building one with keywords goes through ``__init__``, and
    there an undeclared keyword is a caller's typo. Ignoring it would drop the
    value before the request is sent, where the server's own closure cannot
    see it, so construction refuses it the way ``extra="forbid"`` would.

    Pydantic routes validation through a model's ``__init__`` when a class
    overrides it, which would make decoding strict too. Marking the override
    with ``__pydantic_base_init__``, as Pydantic marks ``BaseModel.__init__``
    and ``RootModel.__init__``, keeps ``model_validate``, ``from_dict`` and
    nested decoding on the core validator. ``test_wire_fidelity`` pins both
    halves, so a Pydantic release that changed this would fail there.
    """

    def __init__(self, /, **data: Any) -> None:
        fields = type(self).model_fields
        accepted = set(fields) | {f.alias for f in fields.values() if f.alias}
        unknown: List[InitErrorDetails] = [
            {"type": "extra_forbidden", "loc": (key,), "input": value}
            for key, value in data.items()
            if key not in accepted
        ]
        if unknown:
            raise _PydanticValidationError.from_exception_data(
                type(self).__name__, unknown
            )
        super().__init__(**data)

    __init__.__pydantic_base_init__ = True  # type: ignore[attr-defined]


class _ContextDescriptionMixin(_WireModel):
    """Read the composed scheme's layers off a Context description.

    The wire nests the layers under ``scheme``, which is where the composition
    is recorded. A caller asking what a Context is made of wants them beside
    the guides and crosswalks, so this reads them there. No field is added.
    """

    scheme: Any

    @property
    def layers(self) -> List["ContextComponent"]:
        """The composed scheme's layers in composition order; empty when none."""
        return list(self.scheme.layers or [])


class _KnownOnConstruction:
    """Annotation marker for an open enum on a model that travels both ways.

    The contract is open-response and closed-request. A generated field typed
    ``Union[<known values>, str]`` decodes any string, so a value a newer
    server adds is kept as the string it sent. On a model that callers also
    put in requests, this marker refuses such a value when a caller builds the
    model with keywords, with the ``literal_error`` a closed literal type
    raises, because an undeclared value there is a caller's mistake.

    It also keeps a known value in its declared form: where the known values
    are an ``Enum``, a decoded known string becomes that ``Enum`` member rather
    than the bare string the ``str`` arm would otherwise produce.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        known: List[Any] = []
        members: Dict[Any, Enum] = {}
        pending = list(get_args(source))
        while pending:
            arm = pending.pop(0)
            if isinstance(arm, type) and issubclass(arm, Enum):
                for member in arm:
                    known.append(member.value)
                    members[member.value] = member
            elif get_origin(arm) is Literal:
                known.extend(get_args(arm))
            else:
                pending.extend(get_args(arm))
        expected = _expected(known)

        def check(value: Any) -> Any:
            if isinstance(value, Enum):
                return value
            if value in members:
                return members[value]
            if value is not None and value not in known and _CONSTRUCTING.get():
                raise PydanticKnownError("literal_error", {"expected": expected})
            return value

        return core_schema.no_info_after_validator_function(check, handler(source))


def _expected(values: List[Any]) -> str:
    """Word a value list the way Pydantic's own ``literal_error`` does."""
    quoted = [repr(value) for value in values]
    if len(quoted) <= 1:
        return "".join(quoted)
    return f"{', '.join(quoted[:-1])} or {quoted[-1]}"


_Loc = Tuple[Union[str, int], ...]


def _check_wire_shape(model: str, value: Any) -> None:
    """Refuse a wire value that breaks the contract's required members.

    The shapes are generated into :mod:`ezclassify_rest_client.models` from
    the OpenAPI document's ``required`` lists (see ``WireShapes`` in
    ``scripts/gen_models.py`` for how one reads). A model generated from no
    component has no shape here and is checked by the component around it.

    Raises:
        pydantic.ValidationError: A required member is absent, or is null
            where the contract does not allow null. ``loc`` names it.
    """
    shape = _tables()[1].get(model)
    if shape is None:
        return
    problem = _first_problem(shape, value, ())
    if problem is not None:
        raise _PydanticValidationError.from_exception_data(model, [problem])


def _resolve(shape: Any) -> Any:
    """Follow a shape's component name; a name with no entry requires nothing."""
    while isinstance(shape, str):
        shape = _tables()[0].get(shape)
    return shape


def _tables() -> Tuple[Dict[str, Any], Dict[str, str]]:
    # Bound on first use: models.py imports this module, so the tables do not
    # exist yet when it is first imported.
    global _TABLES
    if _TABLES is None:
        from .models import _MODEL_SHAPES, _WIRE_SHAPES

        _TABLES = (_WIRE_SHAPES, _MODEL_SHAPES)
    return _TABLES


_TABLES: Optional[Tuple[Dict[str, Any], Dict[str, str]]] = None


def _first_problem(shape: Any, value: Any, loc: _Loc) -> Optional[InitErrorDetails]:
    """Walk ``value`` against ``shape`` and report the first broken member."""
    shape = _resolve(shape)
    if shape is None or value is None:
        return None
    if "u" in shape:
        chosen = _alternative(shape["u"], value)
        return None if chosen is None else _first_problem(chosen, value, loc)
    if isinstance(value, dict):
        for name, nullable in shape.get("r", ()):
            if name not in value:
                return {"type": "missing", "loc": loc + (name,), "input": value}
            if value[name] is None and not nullable:
                return {
                    "type": PydanticCustomError(
                        "null_not_allowed",
                        "Input should not be null; the contract requires a value",
                    ),
                    "loc": loc + (name,),
                    "input": None,
                }
        members: Dict[str, Any] = shape.get("p", {})
        for name, member in value.items():
            child = members.get(name)
            if child is None and "v" in shape and name not in shape["d"]:
                child = shape["v"]
            if child is not None:
                problem = _first_problem(child, member, loc + (name,))
                if problem is not None:
                    return problem
    elif isinstance(value, list) and "i" in shape:
        for index, item in enumerate(value):
            problem = _first_problem(shape["i"], item, loc + (index,))
            if problem is not None:
                return problem
    return None


def _alternative(alternatives: List[Dict[str, Any]], value: Any) -> Any:
    """Pick the alternative of a union that ``value`` is, or ``None``.

    That is the first one it satisfies by name: every member it requires is
    present and every member it fixes to a constant or an enum holds one of
    those values. A value that satisfies none is checked against the
    alternative it plainly means, the one whose fixed values it matches and
    whose members it carries the most of, so the member it lacks is the one
    reported. A value that carries none of any alternative's members, or
    contradicts every alternative's fixed values, is a variant this contract
    does not name, and a newer server may send one; it is left to the model,
    as an unknown member would be.
    """
    if isinstance(value, list):
        arrays = [entry for entry in alternatives if entry["k"] == "array"]
        return arrays[0].get("s", arrays[0]) if arrays else None
    if not isinstance(value, dict):
        return None
    members: Dict[str, Any] = value
    best: Optional[Dict[str, Any]] = None
    best_present = 0
    for entry in alternatives:
        if entry["k"] != "object":
            continue
        consts: Dict[str, List[Any]] = entry.get("c", {})
        # A null names no variant, so it contradicts none; the alternative's
        # own check then refuses it if the contract does not allow null.
        if any(
            members.get(name) is not None and members[name] not in allowed
            for name, allowed in consts.items()
        ):
            continue
        required = [name for name, _ in entry.get("r", ())]
        named = set(required) | set(consts)
        present = sum(1 for name in named if name in members)
        if present == len(named):
            return entry.get("s", entry)
        if present > best_present:
            best, best_present = entry, present
    return None if best is None else best.get("s", best)
