"""Public HTTP controls for exclusive text/facts inputs and wire fidelity."""

from __future__ import annotations

import json

import pytest
import respx

from ezclassify_rest_client import (
    EzClassifyClientError,
    EzClassifyContext,
    RestClientCredentials,
    connect_context,
)
from ezclassify_rest_client import Assertion

from .test_context import (
    _BASE,
    _CTX,
    _HDR,
    _VER,
    _ctx_url,
    _describe_route,
    _envelope,
    _validate_result,
)


_ACCESS = "fixture-access"
_CONTEXT = "fixture-context"


def _ctx() -> EzClassifyContext:
    _describe_route()
    return connect_context(
        _BASE,
        context_id=_CTX,
        context_version=_VER,
        credentials=RestClientCredentials(access_token=_ACCESS, context_token=_CONTEXT),
    )


def _suggest_result() -> dict[str, object]:
    return _envelope({"suggestions": [], "warnings": []})


@pytest.mark.parametrize(
    "facts", [[], [Assertion(category_id="level", concept_id="H")]]
)
@respx.mock
def test_facts_suggest_has_no_text_and_preserves_all_remaining_options(
    facts: list[Assertion],
) -> None:
    route = respx.post(_ctx_url("scheme/suggest")).respond(
        200, json=_suggest_result(), headers=_HDR
    )
    with _ctx() as ctx:
        result = ctx.scheme.suggest(
            assertions=facts,
            output_format="",
            surface="portion",
            filter="",
            include_gated=False,
        )
    assert result.result.suggestions == []
    request = route.calls.last.request
    assert json.loads(request.content) == {
        "assertions": [
            fact.model_dump(mode="json", by_alias=True, exclude_none=True)
            for fact in facts
        ],
        "outputFormat": "",
        "surface": "portion",
        "filter": "",
        "includeGated": False,
    }
    assert request.headers["authorization"] == "Bearer fixture-access"
    assert request.headers["x-ezclassify-context-token"] == "fixture-context"


@respx.mock
def test_empty_text_suggest_remains_text_with_a_text_format() -> None:
    route = respx.post(_ctx_url("scheme/suggest")).respond(200, json=_suggest_result())
    with _ctx() as ctx:
        ctx.scheme.suggest("", input_format="portion", include_gated=True)
    assert json.loads(route.calls.last.request.content) == {
        "input": "",
        "inputFormat": "portion",
        "includeGated": True,
    }


@pytest.mark.parametrize("both", [False, True])
@respx.mock
def test_suggest_requires_exactly_one_input_before_transport(both: bool) -> None:
    route = respx.post(_ctx_url("scheme/suggest")).respond(200, json=_suggest_result())
    with (
        _ctx() as ctx,
        pytest.raises(ValueError, match="exactly one of partial or assertions"),
    ):
        if both:
            ctx.scheme.suggest("", assertions=[])
        else:
            ctx.scheme.suggest()
    assert not route.called


@pytest.mark.parametrize("operation", ["suggest", "validate"])
@pytest.mark.parametrize("input_format", ["portion", ""])
@respx.mock
def test_facts_reject_text_only_format_before_transport(
    operation: str,
    input_format: str,
) -> None:
    route = respx.post(_ctx_url("scheme/" + operation)).respond(
        200, json=_suggest_result()
    )
    with (
        _ctx() as ctx,
        pytest.raises(ValueError, match="input_format is only valid with"),
    ):
        getattr(ctx.scheme, operation)(assertions=[], input_format=input_format)
    assert not route.called


@pytest.mark.parametrize(
    "source",
    [
        "parse",
        "user",
        "stated",
        "external-author",
        "infer",
        "default",
        "context",
        "repair",
    ],
)
@respx.mock
def test_source_is_open_and_forwarded_without_sdk_derivation(source: str) -> None:
    fact = Assertion(
        category_id="level",
        concept_id="H",
        source=source,
        replaced_concept_id="OLD",
    )
    route = respx.post(_ctx_url("scheme/suggest")).respond(200, json=_suggest_result())
    with _ctx() as ctx:
        ctx.scheme.suggest(assertions=[fact])
    assert json.loads(route.calls.last.request.content) == {
        "assertions": [fact.model_dump(mode="json", by_alias=True, exclude_none=True)]
    }
    assert fact.source == source and fact.replaced_concept_id == "OLD"


@respx.mock
def test_unknown_output_format_is_an_explicit_error_with_original_request() -> None:
    payload = {
        "error": "Invalid input",
        "code": "INVALID_INPUT",
        "detail": "outputFormat: not-declared",
    }
    route = respx.post(_ctx_url("scheme/suggest")).respond(400, json=payload)
    with _ctx() as ctx, pytest.raises(EzClassifyClientError) as caught:
        ctx.scheme.suggest(assertions=[], output_format="not-declared")
    assert caught.value.status_code == 400
    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.detail == "outputFormat: not-declared"
    assert caught.value.payload == payload
    assert json.loads(route.calls.last.request.content) == {
        "assertions": [],
        "outputFormat": "not-declared",
    }


@respx.mock
def test_raw_closed_body_driver_uses_existing_credentialed_private_transport() -> None:
    payload = {
        "error": "Invalid input",
        "code": "INVALID_INPUT",
        "detail": "request: unexpected property unknownField",
    }
    route = respx.post(_ctx_url("scheme/suggest")).respond(400, json=payload)
    with _ctx() as ctx, pytest.raises(EzClassifyClientError) as caught:
        ctx._send("POST", "scheme/suggest", body={"input": "", "unknownField": False})
    assert caught.value.status_code == 400 and caught.value.payload == payload
    request = route.calls.last.request
    assert json.loads(request.content) == {"input": "", "unknownField": False}
    assert request.headers["authorization"] == "Bearer fixture-access"
    assert request.headers["x-ezclassify-context-token"] == "fixture-context"


@respx.mock
def test_resource_not_found_preserves_the_cached_answer() -> None:
    process = respx.post(_ctx_url("scheme/validate")).respond(
        200, json=_envelope(_validate_result())
    )
    resource = respx.get(_ctx_url("scheme/describe-concept")).respond(
        404, json={"error": "No such concept", "detail": "conceptId: absent"}
    )
    with _ctx() as ctx:
        assert ctx.scheme.validate("H").result.valid is True
        with pytest.raises(EzClassifyClientError) as caught:
            ctx.scheme.describe_concept("absent", "level")
        assert ctx.scheme.validate("H").result.valid is True
    assert resource.call_count == 1 and process.call_count == 1
    assert (
        caught.value.status_code == 404 and caught.value.detail == "conceptId: absent"
    )
