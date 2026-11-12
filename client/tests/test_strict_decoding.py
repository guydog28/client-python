"""``from_dict`` refuses a body that breaks the contract's required members.

The required members come from the OpenAPI document, generated into
``models._WIRE_SHAPES``. These tests pin how ``from_dict`` reads them in the
places a Pydantic model alone cannot: inside members kept as open
dictionaries, inside maps, through a union, and against a construction
default.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from ezclassify_rest_client import (
    Assertion,
    ContextCrosswalkTranslationResult,
    ProcessResult,
)

_ASSESSMENT = {
    "emitted": [],
    "omitted": [],
    "collapsed": [],
    "conflicts": [],
    "unrepresentable": [],
}

_PROCESS = {
    "valid": True,
    "inputWasValid": True,
    "rendered": "H",
    "assertions": [],
    "errors": [],
    "warnings": [],
    "appliedFixes": [],
    "proposedFixes": [],
    "notices": [],
    "assessment": _ASSESSMENT,
    "renders": {"short": {"rendered": "H", "assessment": _ASSESSMENT}},
}


def _refusal(model: type, body: dict) -> dict:
    with pytest.raises(ValidationError) as failure:
        model.from_dict(body)
    error = failure.value.errors()[0]
    return {"loc": error["loc"], "type": error["type"]}


def test_a_complete_body_decodes() -> None:
    assert ProcessResult.from_dict(copy.deepcopy(_PROCESS)).rendered == "H"


def test_a_member_missing_inside_an_open_dictionary_is_refused() -> None:
    body = copy.deepcopy(_PROCESS)
    del body["assessment"]["omitted"]
    assert _refusal(ProcessResult, body) == {
        "loc": ("assessment", "omitted"),
        "type": "missing",
    }
    # Structural validation alone accepts it, which is why from_dict checks.
    assert ProcessResult.model_validate(body).assessment == body["assessment"]


def test_a_member_missing_inside_a_map_value_is_refused() -> None:
    body = copy.deepcopy(_PROCESS)
    del body["renders"]["short"]["assessment"]
    assert _refusal(ProcessResult, body)["loc"] == ("renders", "short", "assessment")


def test_null_where_the_contract_allows_none_is_refused() -> None:
    body = copy.deepcopy(_PROCESS)
    body["assessment"]["emitted"] = None
    assert _refusal(ProcessResult, body) == {
        "loc": ("assessment", "emitted"),
        "type": "null_not_allowed",
    }


def test_a_construction_default_is_not_filled_in_on_decode() -> None:
    body = {"conceptId": "H", "categoryId": "level", "confidence": "certain"}
    assert _refusal(Assertion, body) == {"loc": ("source",), "type": "missing"}
    # Building one with keywords still takes the default.
    assert Assertion(conceptId="H", categoryId="level").source == "parse"


def test_a_union_member_is_checked_against_the_alternative_it_names() -> None:
    artifact = {"kind": "scheme", "id": "s", "version": "1.0.0"}
    forbidden = {
        "status": "forbidden",
        "crosswalk": artifact,
        "sourceScheme": artifact,
        "targetScheme": artifact,
        "source": {k: v for k, v in _PROCESS.items() if k not in ("renders",)},
        "outcomes": [],
        "selections": [],
        "forbiddenBy": [],
    }
    envelope = {
        "resolution": {
            "contextId": "c",
            "resolvedVersion": "1.0.0",
            "artifacts": [],
            "sources": [],
        },
        "operationLimitations": [],
        "result": forbidden,
    }
    assert ContextCrosswalkTranslationResult.from_dict(copy.deepcopy(envelope))
    del envelope["result"]["forbiddenBy"]
    assert _refusal(ContextCrosswalkTranslationResult, envelope)["loc"] == (
        "result",
        "forbiddenBy",
    )


def test_a_union_variant_the_contract_does_not_name_is_left_to_the_model() -> None:
    # A newer server may add a variant; it carries none of the members, or
    # none of the fixed values, of any alternative this contract names.
    envelope = {
        "resolution": {
            "contextId": "c",
            "resolvedVersion": "1.0.0",
            "artifacts": [],
            "sources": [],
        },
        "operationLimitations": [],
        "result": {"status": "deferred", "retryIn": 5},
    }
    decoded = ContextCrosswalkTranslationResult.from_dict(envelope)
    assert decoded.result["status"] == "deferred"
