"""Maintained public operation drivers and explicit private malformed-request seams."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

import httpx
from pydantic import BaseModel

from ezclassify_rest_client import (
    EzClassifyClient,
    EzClassifyContext,
    RestClientCredentials,
)
from ezclassify_rest_client._deadline import _DeadlineTransport
from ezclassify_rest_client.client import _api_error
from ezclassify_rest_contract import Assertion, GuideRuleSelection

from .wire_corpus import WireCase

_CARRIER = "fixture-context-carrier"
_REFUSED = "fixture-refused-bearer"


@contextmanager
def answered_in_process(
    answer: Callable[[httpx.Request], httpx.Response],
) -> Iterator[None]:
    """Answer every request a client sends with ``answer``, with no socket.

    The client's own transport is the only place a request leaves it, so the
    replay stands in there and everything above it runs as it would against
    a server.
    """
    with patch.object(
        _DeadlineTransport,
        "handle_request",
        lambda _transport, request: answer(request),
    ):
        yield


def credentials(case: WireCase) -> RestClientCredentials:
    """Choose the recording's carrier class without inventing secret values."""
    if case.credential == "context-token":
        return RestClientCredentials(context_token=_CARRIER)
    if case.credential == "invalid-bearer":
        return RestClientCredentials(access_token=_REFUSED, context_token=_CARRIER)
    assert case.credential == "none"
    return RestClientCredentials()


def _facts(value: object) -> list[Assertion]:
    assert isinstance(value, list)
    return [Assertion.model_validate(item) for item in value]


def _text(body: dict[str, object], name: str) -> str:
    value = body[name]
    assert isinstance(value, str)
    return value


def _optional_text(body: dict[str, object], name: str) -> str | None:
    value = body.get(name)
    assert value is None or isinstance(value, str)
    return value


def _strings(body: dict[str, object], name: str) -> list[str] | None:
    value = body.get(name)
    assert (
        value is None
        or isinstance(value, list)
        and all(isinstance(item, str) for item in value)
    )
    return value


def _attributes(body: dict[str, object]) -> dict[str, object]:
    value = body["userAttributes"]
    assert isinstance(value, dict)
    return value


def _context(body: dict[str, object]) -> dict[str, object] | None:
    value = body.get("context")
    assert value is None or isinstance(value, dict)
    return value


def _post_with_query(
    ctx: EzClassifyContext, op: str, body: dict[str, object], query: dict[str, str]
) -> object:
    """Send a POST that carries a query, which no public method can build.

    A POST operation declares no query parameter, so the client never sends
    one. The contract records the server's refusal of one, and this seam
    reproduces the request so the replay can check how the client reports it.
    """
    response = ctx._client.post(ctx._op_path(op), json=body, params=query)
    if response.is_error:
        raise _api_error(response)
    return response.json()


def run_context(case: WireCase, ctx: EzClassifyContext) -> object:
    """Call the exact registered public method, or a named literal boundary."""
    path = urlsplit(case.path)
    op = "/".join(path.path.split("/")[5:])
    query = dict(parse_qsl(path.query)) or None
    if case.id in PRIVATE_SEAMS:
        if case.method == "POST":
            assert isinstance(case.body, dict)
            if query is None:
                return ctx._send("POST", op, body=case.body)[0]
            return _post_with_query(ctx, op, case.body, query)
        return ctx._send("GET", op, params=query)[0]
    # A case that names a scheme is a call on that scheme's view; every other
    # scheme case is a call on the primary view, which sends no selector.
    s = ctx.scheme_view(query["scheme"]) if query and "scheme" in query else ctx.scheme
    if case.method == "GET":
        if op == "":
            description = ctx.describe()
            assert ctx.resolved_version == case.response_headers.get(
                "x-ezclassify-resolved-version"
            )
            return description
        if op == "scheme/describe-concept":
            assert query is not None
            return s.describe_concept(
                query["conceptId"], query["categoryId"], view=query.get("view")
            )
        resources = {
            "scheme": s.summary,
            "scheme/concepts": s.concepts,
            "scheme/categories": s.categories,
            "scheme/formats": s.formats,
            "scheme/grammar": s.grammar,
            "scheme/scopes": s.scopes,
            "scheme/label-presets": s.label_presets,
            "access/rules": ctx.access.rules,
            "crosswalk/describe": ctx.crosswalk.describe,
        }
        return resources[op]()
    body = case.body
    assert isinstance(body, dict)
    if op == "scheme/process":
        return s.process(
            _text(body, "input"),
            output_format=_optional_text(body, "outputFormat"),
            surface=_optional_text(body, "surface"),
            input_format=_optional_text(body, "inputFormat"),
            outputs=_strings(body, "outputs"),
            suggest_for=_strings(body, "suggestFor"),
        )
    if op == "scheme/validate":
        if "assertions" in body:
            return s.validate(
                assertions=_facts(body["assertions"]),
                output_format=_optional_text(body, "outputFormat"),
                surface=_optional_text(body, "surface"),
            )
        return s.validate(
            _text(body, "input"),
            input_format=_optional_text(body, "inputFormat"),
            output_format=_optional_text(body, "outputFormat"),
            surface=_optional_text(body, "surface"),
        )
    if op == "scheme/suggest":
        include_gated = body.get("includeGated")
        assert include_gated is None or isinstance(include_gated, bool)
        if "assertions" in body:
            return s.suggest(
                assertions=_facts(body["assertions"]),
                output_format=_optional_text(body, "outputFormat"),
                surface=_optional_text(body, "surface"),
                filter=_optional_text(body, "filter"),
                include_gated=include_gated,
            )
        return s.suggest(
            _text(body, "input"),
            input_format=_optional_text(body, "inputFormat"),
            output_format=_optional_text(body, "outputFormat"),
            surface=_optional_text(body, "surface"),
            filter=_optional_text(body, "filter"),
            include_gated=include_gated,
        )
    if op == "scheme/suggest-for-categories":
        categories = _strings(body, "categoryIds")
        assert categories is not None
        return s.suggest_for_categories(_facts(body["assertions"]), categories)
    if op == "scheme/apply-preset":
        return s.apply_preset(
            _text(body, "presetId"), output_format=_optional_text(body, "outputFormat")
        )
    if op == "scheme/explain":
        return s.explain(_text(body, "input"))
    if op == "scheme/normalize":
        return s.normalize(_text(body, "input"))
    if op == "scheme/render":
        return s.render(
            _facts(body["assertions"]),
            output_format=_optional_text(body, "outputFormat"),
        )
    if op == "scheme/diff":
        return s.diff(_text(body, "a"), _text(body, "b"))
    if op == "scheme/view":
        return s.view()
    if op == "scheme/notices":
        return s.notices(_facts(body["assertions"]))
    if op == "scheme/filter-concepts":
        return s.filter_concepts(_text(body, "query"))
    if op == "scheme/scan":
        return s.scan(_text(body, "text"))
    if op == "scheme/aggregate":
        if "assertionSets" in body:
            sets = body["assertionSets"]
            assert isinstance(sets, list)
            return s.aggregate_assertions([_facts(item) for item in sets])
        inputs = _strings(body, "inputs")
        assert inputs is not None
        return s.aggregate(inputs)
    if op == "scheme/check-coverage":
        children = _strings(body, "children")
        assert children is not None
        return s.check_coverage(children, _text(body, "parent"))
    if op == "access/check":
        if "assertions" in body:
            return ctx.access.check(
                _facts(body["assertions"]), _attributes(body), context=_context(body)
            )
        return ctx.access.check_by_marking(
            _text(body, "marking"), _attributes(body), context=_context(body)
        )
    if op == "access/describe-rule":
        return ctx.access.describe_rule(_text(body, "ruleId"))
    if op == "access/describe-requirements":
        return ctx.access.describe_requirements(_text(body, "marking"))
    if op == "guide/scan":
        return ctx.guide.scan(_text(body, "text"))
    if op == "guide/evaluate":
        if "selections" in body:
            return ctx.guide.evaluate_many(
                *(
                    GuideRuleSelection.model_validate(item)
                    for item in body["selections"]
                )
            )
        rules = _strings(body, "selectedRuleIds")
        assert rules is not None
        return ctx.guide.evaluate(_text(body, "guideId"), *rules)
    if op == "guide/describe-rule":
        return ctx.guide.describe_rule(
            _text(body, "ruleId"), _optional_text(body, "guideId")
        )
    if op == "guide/view":
        return ctx.guide.view(_optional_text(body, "guideId"))
    if op == "guide/filter-rules":
        return ctx.guide.filter_rules(_text(body, "query"))
    if op == "crosswalk/translate":
        if "assertions" in body:
            return ctx.crosswalk.translate(
                _text(body, "crosswalkId"), assertions=_facts(body["assertions"])
            )
        return ctx.crosswalk.translate(
            _text(body, "crosswalkId"), marking=_text(body, "marking")
        )
    if op == "document/audit":
        profile = _optional_text(body, "responseProfile")
        assert profile in (None, "summary", "standard", "full")
        return ctx.document.audit(_text(body, "text"), response_profile=profile)
    raise AssertionError(f"no public driver for {case.id}: {op}")


def run_deployment(case: WireCase, client: EzClassifyClient) -> object:
    """Use discovery/health adapters where declared; raw routes stay private."""
    if case.id in PRIVATE_SEAMS:
        # The raw route: no public method sends it, so no model decodes it.
        headers = client._request_headers(case.path)
        if case.credential == "context-token":
            # Raw undeclared-route probes reproduce their explicit carrier;
            # normal SDK routing still keeps it off non-Context operations.
            headers["x-ezclassify-context-token"] = _CARRIER
        response = client._client.get(case.path, headers=headers)
        if response.is_error:
            raise _api_error(response)
        return response.json()
    if case.path == "/v1/health":
        ping = client.ping()
        assert isinstance(case.response_body, dict)
        assert ping.engine_version == case.response_body["engineVersion"]
        assert ping.engine_sha == case.response_body["engineSha"]
        assert ping.git_tag == case.response_body["gitTag"]
        return None
    if case.path == "/v1/ctx":
        return client.list_contexts()
    return client.list_context_versions(case.path.rsplit("/", 1)[1])


def wire_value(value: object) -> object:
    """Recover populated wire fields, including unknown response properties."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if isinstance(value, list):
        return [wire_value(item) for item in value]
    return value


# Why a recorded case cannot go through a public method. Every case not listed
# in PRIVATE_SEAMS is driven through one, and test_spec_operation_coverage
# holds both halves: a new case needs a public driver or a reason here, and a
# listed case has to be one no public method can send.
UNBUILDABLE_REQUEST = (
    "The typed signature cannot build this body or query, so the runtime's "
    "refusal of a hand-built request is replayed raw."
)
UNDECLARED_ROUTE = (
    "The route or method is not one the contract declares, so no public method "
    "reaches it."
)
UNSENT_OPERATION = (
    "The client deliberately never sends this operation; NOT_SENT in "
    "test_spec_operation_coverage says why."
)

PRIVATE_SEAMS: dict[str, str] = {
    "ready.ok": UNSENT_OPERATION,
    "method-guard.allow-header": UNDECLARED_ROUTE,
    "route-miss.ctx-operation-not-found": UNDECLARED_ROUTE,
    "route-miss.route-not-found": UNDECLARED_ROUTE,
    "ctx-scheme-validate.both-sources": UNBUILDABLE_REQUEST,
    "ctx-scheme-validate.no-source": UNBUILDABLE_REQUEST,
    "ctx-scheme-aggregate.input-format-with-sets": UNBUILDABLE_REQUEST,
    "ctx-scheme-suggest.both-sources": UNBUILDABLE_REQUEST,
    "ctx-scheme-suggest.no-source": UNBUILDABLE_REQUEST,
    "ctx-scheme-suggest.input-format-with-facts": UNBUILDABLE_REQUEST,
    "ctx-crosswalk-translate.both-sources": UNBUILDABLE_REQUEST,
    "ctx-crosswalk-translate.no-source": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-fix": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-preserveDeprecated": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-normalization": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-skipRepair": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-skipInference": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-tolerant": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-validateOnly": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-scope": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-format": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-repairStrategy": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-request-field-unknownField": UNBUILDABLE_REQUEST,
    "ctx-scheme-validate.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-explain.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-normalize.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-aggregate.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-suggest.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-suggest-for-categories.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-render.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-scan.undeclared-field": UNBUILDABLE_REQUEST,
    "ctx-document-audit.undeclared-guide-field": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.missing-input": UNBUILDABLE_REQUEST,
    "ctx-scheme-label-presets.undeclared-query-parameter": UNBUILDABLE_REQUEST,
    "ctx-scheme-process.undeclared-query-parameter": UNBUILDABLE_REQUEST,
    "health.undeclared-query-parameter": UNBUILDABLE_REQUEST,
}
