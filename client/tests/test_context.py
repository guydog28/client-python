"""Tests for the context-bound client surface (connect_context + ctx sub-clients).

Uses respx to mock the HTTP layer; no live server required. The stub stamps the
X-EzClassify-Resolved-Version header so the wrapper can surface it, and every
test asserts the request hit the /v1/ctx/{id}/{version}/* path.
"""

from __future__ import annotations

import json

import httpx
import pytest

import respx

from ezclassify_rest_client import (
    EzClassifyClient,
    EzClassifyClientError,
    EzClassifyContext,
    MalformedResponseError,
    RestClientCredentials,
    connect_context,
)
from ezclassify_rest_contract import (
    Assertion,
    CategoryView,
    ConceptView,
    ContextAccessDecisionResult,
    ContextAccessRequirementsResult,
    ContextAccessRuleDescriptionResult,
    ContextCrosswalkTranslationResult,
    ContextDescription,
    ContextDocumentAuditResult,
    ContextGuideEvaluationResult,
    ContextGuideFilterRulesResult,
    ContextGuideRuleDescriptionResult,
    ContextGuideScanResult,
    ContextGuideViewResult,
    ContextSchemeAggregateResult,
    ContextSchemeConceptDescriptionResult,
    ContextSchemeCoverageResult,
    ContextSchemeDiffResult,
    ContextSchemeExplainResult,
    ContextSchemeFilterConceptsResult,
    ContextSchemeNormalizeResult,
    ContextSchemeNoticesResult,
    ContextSchemeProcessResult,
    ContextSchemeRenderResult,
    ContextSchemeScanResult,
    ContextSchemeSuggestForCategoriesResult,
    ContextSchemeSuggestResult,
    CtxAccessRulesResponseBody,
    ContextSchemeValidateResult,
    ContextSchemeViewResult,
    LabelPresetView,
    SchemeScope,
)

from .test_request_schema_conformance import OpenApiRequestSchemas

_BASE = "http://localhost:9999"
_CTX = "acme-ctx"
_VER = "1.0.0"
_HDR = {"X-EzClassify-Resolved-Version": "9.9.9"}
_RESOLVED = "X-EzClassify-Resolved-Version"


def _artifact(kind: str, artifact_id: str) -> dict:
    return {"kind": kind, "id": artifact_id, "version": "1.0.0"}


def _rule(kind: str, artifact_id: str, rule_id: str = "r1") -> dict:
    return {
        "artifact": _artifact(kind, artifact_id),
        "ruleId": rule_id,
        "ruleDigest": f"sha256:{rule_id}",
    }


def _access_result(granted: bool = True) -> dict:
    return {
        "name": "Clr",
        "granted": granted,
        "skipped": False,
        "ruleIndex": 0,
        "activation": {"matched": True, "assertions": [], "contextPaths": []},
        "comparisons": [],
        "rule": _rule("access", "ap"),
    }


def _envelope(result: object) -> dict:
    return {
        "resolution": {
            "contextId": _CTX,
            "resolvedVersion": "9.9.9",
            "artifacts": [],
            "sources": [],
        },
        "operationLimitations": [],
        "result": result,
    }


_ASSESSMENT = {
    "emitted": [],
    "omitted": [],
    "collapsed": [],
    "conflicts": [],
    "unrepresentable": [],
}


def _validate_result(**overrides: object) -> dict:
    """What validate answers: the facts, both verdicts, one rendering."""
    result = {
        "valid": True,
        "rendered": "H",
        "inputWasValid": True,
        "assertions": [],
        "errors": [],
        "warnings": [],
        "appliedFixes": [],
        "assessment": _ASSESSMENT,
        "recognition": {"status": "complete", "surface": "marking", "unmatched": []},
        "notices": [],
    }
    result.update(overrides)
    return result


def _process_result(**overrides: object) -> dict:
    """What process answers: the validate answer plus the authoring answers."""
    result = _validate_result(
        recognition={
            "status": "complete",
            "surface": "marking",
            "unmatched": [],
            "corrections": [],
        },
        proposedFixes=[],
        renders={},
    )
    result.update(overrides)
    return result


def _aggregate_result(**overrides: object) -> dict:
    result = _validate_result(proposedFixes=[])
    for member in ("inputWasValid", "assessment", "recognition"):
        result.pop(member)
    result.update(overrides)
    return result


def _trace(**overrides: object) -> dict:
    """What explain answers: the step-by-step trace of one process call."""
    trace = {
        "input": "H",
        "schemeId": "levels",
        "entries": [],
        "repairs": [],
        "validationErrors": [],
        "inferences": [],
        "finalAssertions": [],
        "rendered": "H",
    }
    trace.update(overrides)
    return trace


def _full_trace() -> dict:
    """A trace with one of everything it can hold."""
    return _trace(
        entries=[
            {
                "stage": "infer",
                "action": "add",
                "detail": "Added STAFF.",
                "conceptId": "STAFF",
                "conceptName": "STAFF",
                "categoryId": "audience",
                "ruleId": "high-needs-staff",
                "triggerConceptIds": ["H"],
            }
        ],
        repairs=[
            {
                "ruleId": "upper-case",
                "description": "Writes the level in capitals.",
                "confidence": "safe",
                "before": "h",
                "after": "H",
                "cosmetic": True,
            }
        ],
        validationErrors=[{"constraintId": "needs-staff", "message": "H needs STAFF."}],
        inferences=[
            {
                "ruleId": "high-needs-staff",
                "conceptId": "STAFF",
                "conceptName": "STAFF",
                "explanation": "H requires STAFF.",
            }
        ],
    )


def _descriptor(component_id: str, version: str = "9.9.9") -> dict:
    """A component reference as the describe body echoes it."""
    return {"id": component_id, "version": "latest", "resolvedVersion": version}


def _describe_body(ctx_id: str = _CTX, version: str = _VER) -> dict:
    """What describing a Context answers: its components, crosswalks included."""
    return {
        "id": ctx_id,
        "version": version,
        "scheme": _descriptor("levels"),
        "schemes": [
            {
                "selector": "levels",
                "id": "levels",
                "version": "9.9.9",
                "roles": ["primary"],
            },
            {
                "selector": "legacy",
                "id": "legacy",
                "version": "2.0.0",
                "roles": ["crosswalk-source"],
            },
        ],
        "guides": [_descriptor("handling")],
        "access": _descriptor("clearance"),
        "crosswalks": [
            _descriptor("levels-to-legacy"),
            _descriptor("legacy-to-levels"),
        ],
    }


def _translation() -> dict:
    """A completed crosswalk translation with every member the contract requires."""
    return {
        "status": "completed",
        "crosswalk": _artifact("crosswalk", "state-to-district"),
        "sourceScheme": _artifact("scheme", "state"),
        "targetScheme": _artifact("scheme", "district"),
        "source": _validate_result(),
        "target": _validate_result(),
        "outcomes": [],
        "selections": [],
    }


def _guide_rule_view(rule_id: str) -> dict:
    """A guide rule as a guide view lists it, with only its required members."""
    return {
        "id": rule_id,
        "name": rule_id,
        "outcomeText": "",
        "isComputed": False,
        "keywords": [],
        "matcherLabels": [],
        "dependsOn": [],
        "dependsOnNames": [],
        "overrides": [],
        "overrideNames": [],
    }


def _concept_view(**overrides: object) -> dict:
    """A concept with only the members the contract requires."""
    concept = {
        "id": "L_H",
        "name": "High",
        "views": {"default": "High"},
        "aliases": [],
        "categories": ["level"],
        "parents": [],
        "position": 1,
    }
    concept.update(overrides)
    return concept


def _full_concept_view() -> dict:
    """A concept with every optional member populated."""
    return _concept_view(
        rank=10,
        tier="top",
        members=["L_H1"],
        scopes=["doc"],
        deprecated=False,
        deprecatedMessage="Use L_X.",
        deprecatedReplacement="L_X",
        definition="The high level.",
        citation="Section 3",
        guidance="Use sparingly.",
        rulesReferencing=["H needs STAFF."],
        textInput={"placeholder": "name", "label": "Name", "required": True},
    )


def _category_view(**overrides: object) -> dict:
    """A category with only the members the contract requires."""
    category = {"id": "level", "label": "Level", "rollup": "max"}
    category.update(overrides)
    return category


def _full_category_view() -> dict:
    """A category with every optional member populated."""
    return _category_view(
        required=True,
        single=True,
        sort=["position", "alphabetical"],
        positionOverrides={"L_H": 2},
        scopes=["doc"],
        position=1,
        hierarchyRoot=False,
        defaultConcept="L_H",
    )


def _format_view(**overrides: object) -> dict:
    """A format with only the members the contract requires."""
    view = {
        "id": "banner",
        "surface": "whole",
        "mode": "inline",
        "categoryOrder": ["level"],
    }
    view.update(overrides)
    return view


def _label_preset_view() -> dict:
    return {
        "id": "default-label",
        "label": "Default",
        "description": "d",
        "scope": "doc",
    }


class TestFixturesMatchTheContract:
    """The response fixtures above are hand-written, so hold them to the contract.

    Result models decode open, so a fixture that kept a member the contract
    has dropped, or lost one it requires, would still decode, and every test
    built on it would pass against a shape no server sends. Each builder is
    checked against its component with every object closed.
    """

    @pytest.mark.parametrize(
        ("component", "build"),
        [
            ("ValidateResult", _validate_result),
            ("ProcessResult", _process_result),
            ("AggregateResult", _aggregate_result),
            ("ExplanationTrace", _trace),
            ("ExplanationTrace", _full_trace),
            ("MarkingValidation", lambda: _audit_validation("H")),
            ("AccessRuleResult", _access_result),
            ("CtxDescribeResponseBody", _describe_body),
            ("ConceptView", _concept_view),
            ("ConceptView", _full_concept_view),
            ("CategoryView", _category_view),
            ("CategoryView", _full_category_view),
            ("FormatView", _format_view),
            ("LabelPresetView", _label_preset_view),
        ],
    )
    def test_each_result_fixture_is_what_the_contract_declares(
        self, contract, component, build
    ):
        assert contract.validate_closed(component, build()) == []

    def test_the_closed_check_refuses_an_undeclared_member(self, contract):
        undeclared = _process_result(notAMember={"entries": []})
        errors = contract.validate_closed("ProcessResult", undeclared)
        assert errors == ["$: property 'notAMember' is not allowed by the contract"]


@pytest.fixture(scope="module")
def contract() -> OpenApiRequestSchemas:
    """The vendored OpenAPI document, read once for the fixture checks."""
    return OpenApiRequestSchemas.load()


def _describe_route(ctx_id: str = _CTX, version: str = _VER):
    """Register the connect-time describe probe (GET /v1/ctx/{id}/{version})."""
    return respx.get(f"{_BASE}/v1/ctx/{ctx_id}/{version}").mock(
        return_value=httpx.Response(
            200, json=_describe_body(ctx_id, version), headers=_HDR
        )
    )


def _ctx_url(op: str) -> str:
    return f"{_BASE}/v1/ctx/{_CTX}/{_VER}/{op}"


class TestContextProperties:
    @respx.mock
    def test_context_id_property(self):
        ctx = _connect()
        assert ctx.context_id == _CTX
        ctx.close()

    @respx.mock
    def test_context_manager_closes_transport_on_exit(self):
        _describe_route()
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            assert not ctx._client.is_closed
        assert ctx._client.is_closed


class TestConnect:
    @respx.mock
    def test_an_omitted_version_lets_the_server_choose(self):
        # No token: the server answers with its newest published version.
        describe = respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest").mock(
            return_value=httpx.Response(
                200, json=_describe_body(), headers={_RESOLVED: "2.4.0"}
            )
        )
        process = respx.post(f"{_BASE}/v1/ctx/{_CTX}/scheme/process").mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers={_RESOLVED: "2.4.0"}
            )
        )
        with connect_context(_BASE, context_id=_CTX) as ctx:
            assert ctx.version is None
            assert ctx.resolved_version == "2.4.0"
            ctx.scheme.process("H")
            ctx.describe()
        # The bare Context URL lists versions, so describing asks for latest,
        # which the server resolves exactly as it resolves an omitted version.
        assert [call.request.url.path for call in describe.calls] == [
            f"/v1/ctx/{_CTX}/latest",
            f"/v1/ctx/{_CTX}/latest",
        ]
        assert "x-ezclassify-context-token" not in process.calls.last.request.headers

    @pytest.mark.parametrize("version", [None, ""])
    def test_an_empty_or_missing_version_is_omitted(self, version):
        ctx = EzClassifyContext(_BASE, context_id=_CTX, context_version=version)
        assert ctx.version is None
        assert ctx._op_path("scheme/process") == f"/v1/ctx/{_CTX}/scheme/process"
        ctx.close()

    @respx.mock
    def test_latest_by_name_is_carried_in_every_path(self):
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest").mock(
            return_value=httpx.Response(
                200, json=_describe_body(), headers={_RESOLVED: "2.4.0"}
            )
        )
        process = respx.post(f"{_BASE}/v1/ctx/{_CTX}/latest/scheme/process").mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers={_RESOLVED: "2.4.0"}
            )
        )
        with connect_context(_BASE, context_id=_CTX, context_version="latest") as ctx:
            assert ctx.version == "latest"
            ctx.scheme.process("H")
        assert process.called

    @respx.mock
    def test_resolves_via_describe_endpoint(self):
        route = _describe_route()
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        assert route.called
        assert route.calls.last.request.method == "GET"
        assert route.calls.last.request.url.path == f"/v1/ctx/{_CTX}/{_VER}"
        assert ctx.resolved_version == "9.9.9"
        ctx.close()

    @respx.mock
    def test_connects_to_a_context_whose_describe_lists_crosswalks(self):
        route = _describe_route()
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            assert ctx.resolved_version == "9.9.9"
        described = json.loads(route.calls.last.response.content)
        assert [c["id"] for c in described["crosswalks"]] == [
            "levels-to-legacy",
            "legacy-to-levels",
        ]

    @respx.mock
    def test_encodes_special_chars_in_path(self):
        route = respx.get(url__regex=r".*/v1/ctx/.*").mock(
            return_value=httpx.Response(200, json=_describe_body(), headers=_HDR)
        )
        connect_context(
            _BASE, context_id="tenant a/marking", context_version="0.1.0+gov"
        )
        url = str(route.calls.last.request.url)
        assert "/v1/ctx/tenant%20a%2Fmarking/0.1.0%2Bgov" in url


def _connect():
    _describe_route()
    return connect_context(_BASE, context_id=_CTX, context_version=_VER)


class TestDescribe:
    """``describe`` answers what the Context is made of, typed, on every call."""

    @respx.mock
    def test_reads_every_component_with_declared_and_resolved_versions(self):
        route = _describe_route()
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            description = ctx.describe()
        assert route.call_count == 2  # connect, then this call
        assert isinstance(description, ContextDescription)
        assert (description.id, description.version) == (_CTX, _VER)
        assert description.scheme.id == "levels"
        assert description.scheme.version == "latest"
        assert description.scheme.resolved_version == "9.9.9"
        assert [g.id for g in description.guides] == ["handling"]
        assert description.access is not None and description.access.id == "clearance"
        assert [c.id for c in description.crosswalks] == [
            "levels-to-legacy",
            "legacy-to-levels",
        ]
        assert all(c.resolved_version == "9.9.9" for c in description.crosswalks)
        assert [(x.selector, x.roles) for x in description.schemes] == [
            ("levels", ["primary"]),
            ("legacy", ["crosswalk-source"]),
        ]

    @respx.mock
    def test_layers_are_the_composed_schemes_layers_in_order(self):
        body = _describe_body()
        body["scheme"]["layers"] = [_descriptor("base"), _descriptor("overlay")]
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            return_value=httpx.Response(200, json=body, headers=_HDR)
        )
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            layers = ctx.describe().layers
        assert [layer.id for layer in layers] == ["base", "overlay"]
        assert layers[1].resolved_version == "9.9.9"

    @respx.mock
    def test_a_context_that_declares_nothing_optional_answers_empty_collections(self):
        body = _describe_body()
        for member in ("guides", "access", "crosswalks"):
            del body[member]
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            return_value=httpx.Response(200, json=body, headers=_HDR)
        )
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            description = ctx.describe()
        assert description.guides == [] and description.crosswalks == []
        assert description.layers == [] and description.access is None

    @respx.mock
    def test_each_call_makes_a_request_and_clear_cache_has_nothing_to_drop(self):
        route = _describe_route()
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            ctx.describe()
            ctx.describe()
            ctx.clear_cache()
            ctx.describe()
        assert route.call_count == 4

    @respx.mock
    def test_a_body_that_is_not_a_description_is_refused(self):
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            side_effect=[
                httpx.Response(200, json=_describe_body(), headers=_HDR),
                httpx.Response(200, json={"id": _CTX}, headers=_HDR),
            ]
        )
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            with pytest.raises(MalformedResponseError) as raised:
                ctx.describe()
        assert raised.value.path == "$.version"

    @respx.mock
    def test_connect_refuses_a_description_the_contract_does_not_allow(self):
        body = _describe_body()
        body["scheme"].pop("resolvedVersion")
        route = respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            return_value=httpx.Response(200, json=body, headers=_HDR)
        )
        with pytest.raises(MalformedResponseError) as raised:
            connect_context(_BASE, context_id=_CTX, context_version=_VER)
        assert raised.value.path == "$.scheme.resolvedVersion"
        assert route.call_count == 1

    @respx.mock
    def test_an_unknown_context_raises_the_client_error(self):
        route = respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            side_effect=[
                httpx.Response(200, json=_describe_body(), headers=_HDR),
                httpx.Response(404, json={"error": "No such context"}, headers=_HDR),
            ]
        )
        with connect_context(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            with pytest.raises(EzClassifyClientError) as caught:
                ctx.describe()
        assert caught.value.status_code == 404
        assert route.call_count == 2


class TestTokenDefaultedBinding:
    """With a context token, an omitted version is the token's default."""

    _TOKEN = RestClientCredentials(context_token="signed-context-token")

    @respx.mock
    def test_operations_carry_no_version_segment(self):
        describe = respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest").mock(
            return_value=httpx.Response(
                200, json=_describe_body(), headers={_RESOLVED: "3.1.0"}
            )
        )
        process = respx.post(f"{_BASE}/v1/ctx/{_CTX}/scheme/process").mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers={_RESOLVED: "3.1.0"}
            )
        )
        with connect_context(_BASE, context_id=_CTX, credentials=self._TOKEN) as ctx:
            assert ctx.version is None and ctx.resolved_version == "3.1.0"
            ctx.scheme.process("H")
        # The bare Context URL lists versions, so the description asks for latest.
        assert describe.call_count == 1
        assert process.calls.last.request.headers["x-ezclassify-context-token"] == (
            "signed-context-token"
        )

    def test_decision_caching_is_refused(self):
        with pytest.raises(ValueError, match="concrete Context version"):
            EzClassifyContext(
                _BASE,
                context_id=_CTX,
                context_version=None,
                credentials=self._TOKEN,
                cache_access_decisions=True,
            )

    @respx.mock
    def test_entries_expire_like_latest(self, monkeypatch):
        from ezclassify_rest_client import _response_cache

        clock = [10.0]
        monkeypatch.setattr(_response_cache, "monotonic", lambda: clock[0])
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest").mock(
            return_value=httpx.Response(
                200, json=_describe_body(), headers={_RESOLVED: "3.1.0"}
            )
        )
        process = respx.post(f"{_BASE}/v1/ctx/{_CTX}/scheme/process").mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers={_RESOLVED: "3.1.0"}
            )
        )
        with connect_context(
            _BASE, context_id=_CTX, context_version=None, credentials=self._TOKEN
        ) as ctx:
            ctx.scheme.process("H")
            ctx.scheme.process("H")
            assert process.call_count == 1
            clock[0] += 3601.0
            ctx.scheme.process("H")
        assert process.call_count == 2


class TestResponseCache:
    @respx.mock
    def test_repeated_process_reads_make_one_wire_request(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        with _connect() as ctx:
            assert ctx.scheme.process("H").result.rendered == "H"
            assert ctx.scheme.process("H").result.rendered == "H"
            assert route.call_count == 1
            ctx.scheme.process("OTHER")
            assert route.call_count == 2

    @respx.mock
    def test_key_uses_canonical_body_and_keeps_distinct_inputs(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        with _connect() as ctx:
            ctx.scheme.process("H", context={"a": 1, "b": 2})
            ctx.scheme.process("H", context={"b": 2, "a": 1})
            assert route.call_count == 1
            ctx.scheme.process("H", context={"a": 1, "b": None})
            assert route.call_count == 2

    def test_the_cached_operations_are_the_set_every_sdk_caches(self):
        # Every EzClassify client caches the same operations, no wider and no
        # narrower, so an integrator moving between SDKs gets the same number
        # of round trips.
        from ezclassify_rest_client import context

        assert set(context._CACHED_POSTS) == {
            "scheme/process",
            "scheme/validate",
            "scheme/explain",
            "scheme/normalize",
            "scheme/render",
            "scheme/diff",
            "scheme/aggregate",
            "scheme/apply-preset",
            "scheme/suggest",
            "scheme/suggest-for-categories",
            "scheme/scan",
        }
        assert set(context._CACHED_GETS) == {
            "scheme/describe-concept",
            "access/rules",
        }

    @respx.mock
    def test_every_request_field_that_changes_the_answer_is_in_the_key(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        with _connect() as ctx:
            ctx.scheme.process("H")
            ctx.scheme.process("H", outputs=["marking/short"])
            ctx.scheme.process("H", outputs=["marking/long"])
            ctx.scheme.process("H", outputs=["marking/long", "marking/short"])
            ctx.scheme.process("H", suggest_for=["level"])
            ctx.scheme.process("H", input_format="short")
            ctx.scheme.process("H", output_format="marking/long")
            ctx.scheme.process("H", surface="portion")
            ctx.scheme.process("H", parts=["L"])
            ctx.scheme.process("H", context={"role": "part"})
            ctx.scheme.process(
                "H", assertions=[Assertion(categoryId="level", conceptId="H")]
            )
            assert route.call_count == 11
            # The same request again, in any keyword order, is already held.
            ctx.scheme.process("H", suggest_for=["level"])
            ctx.scheme.process("H", outputs=["marking/long", "marking/short"])
            assert route.call_count == 11

    @respx.mock
    def test_validate_given_text_and_given_facts_are_different_requests(self):
        route = respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result()), headers=_HDR
            )
        )
        facts = [Assertion(categoryId="level", conceptId="H")]
        with _connect() as ctx:
            ctx.scheme.validate("H")
            ctx.scheme.validate(assertions=facts)
            ctx.scheme.validate("H", context={"role": "part"})
            ctx.scheme.validate("H", parts=["L"])
            assert route.call_count == 4
            ctx.scheme.validate("H")
            ctx.scheme.validate(assertions=facts)
            assert route.call_count == 4

    @respx.mock
    def test_explain_is_cached_apart_from_process_for_the_same_body(self):
        process = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        explain = respx.post(_ctx_url("scheme/explain")).mock(
            return_value=httpx.Response(200, json=_envelope(_trace()), headers=_HDR)
        )
        with _connect() as ctx:
            assert isinstance(ctx.scheme.process("H"), ContextSchemeProcessResult)
            assert isinstance(ctx.scheme.explain("H"), ContextSchemeExplainResult)
            ctx.scheme.process("H")
            ctx.scheme.explain("H")
            assert json.loads(process.calls.last.request.content) == json.loads(
                explain.calls.last.request.content
            )
            assert process.call_count == 1
            assert explain.call_count == 1

    @respx.mock
    def test_suggest_for_categories_is_cached_by_its_categories(self):
        route = respx.post(_ctx_url("scheme/suggest-for-categories")).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=_envelope(
                    {
                        category: {"suggestions": [], "warnings": []}
                        for category in json.loads(request.content)["categoryIds"]
                    }
                ),
                headers=_HDR,
            )
        )
        with _connect() as ctx:
            ctx.scheme.suggest_for_categories([], ["level"])
            ctx.scheme.suggest_for_categories([], ["level"])
            assert route.call_count == 1
            ctx.scheme.suggest_for_categories([], ["level", "audience"])
            assert route.call_count == 2

    @respx.mock
    def test_access_decisions_still_make_one_request_per_decision(self):
        route = respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"granted": True, "rules": [], "warnings": []}),
                headers=_HDR,
            )
        )
        with _connect() as ctx:
            assert ctx.access.check([], {}).result.granted
            assert ctx.access.check([], {}).result.granted
            assert route.call_count == 2

    @respx.mock
    def test_access_decision_opt_in_requires_a_pin_and_can_be_cleared(self):
        route = respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"granted": True, "rules": [], "warnings": []}),
                headers=_HDR,
            )
        )
        with pytest.raises(ValueError, match="concrete Context version"):
            connect_context(_BASE, context_id=_CTX, cache_access_decisions=True)
        _describe_route()
        with EzClassifyClient(_BASE) as deployment:
            with deployment.context(_CTX, _VER, cache_access_decisions=True) as ctx:
                assert ctx.access.check([], {}).result.granted
                assert ctx.access.check([], {}).result.granted
                assert route.call_count == 1
                assert ctx.access.check_by_marking("H", {}).result.granted
                assert ctx.access.check_by_marking("H", {}).result.granted
                assert route.call_count == 2
                ctx.clear_cache()
                assert ctx.access.check([], {}).result.granted
                assert route.call_count == 3

    @respx.mock
    def test_a_caller_mutating_its_result_cannot_change_what_others_hold(self):
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        with _connect() as ctx:
            first = ctx.scheme.process("H")
            assert first.result.recognition is not None
            first.result.recognition["corrections"].append({"edited": True})
            first.result.recognition["unmatched"].append("edited")
            second = ctx.scheme.process("H")
            assert second.result.recognition is not None
            assert second.result.recognition["corrections"] == []
            assert second.result.recognition["unmatched"] == []

    @respx.mock
    def test_malformed_success_is_not_retained(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            side_effect=[
                httpx.Response(200, json={"result": {}}, headers=_HDR),
                httpx.Response(200, json=_envelope(_process_result()), headers=_HDR),
            ]
        )
        with _connect() as ctx:
            with pytest.raises(MalformedResponseError) as raised:
                ctx.scheme.process("H")
            assert raised.value.path == "$.resolution"
            assert ctx.scheme.process("H").result.rendered == "H"
            assert route.call_count == 2

    @respx.mock
    def test_latest_response_expires_and_version_change_clears_prior_reads(
        self, monkeypatch
    ):
        from ezclassify_rest_client import _response_cache

        clock = [1_000.0]
        monkeypatch.setattr(_response_cache, "monotonic", lambda: clock[0])
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest").mock(
            return_value=httpx.Response(
                200, json=_describe_body(), headers={_RESOLVED: "1.0.0"}
            )
        )
        route = respx.post(f"{_BASE}/v1/ctx/{_CTX}/latest/scheme/process").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_envelope(_process_result()),
                    headers={_RESOLVED: "1.0.0"},
                ),
                httpx.Response(
                    200,
                    json=_envelope(_process_result()),
                    headers={_RESOLVED: "2.0.0"},
                ),
                httpx.Response(
                    200,
                    json=_envelope(_process_result()),
                    headers={_RESOLVED: "2.0.0"},
                ),
            ]
        )
        rules = respx.get(f"{_BASE}/v1/ctx/{_CTX}/latest/access/rules").mock(
            side_effect=[
                httpx.Response(200, json={"rules": []}, headers={_RESOLVED: "1.0.0"}),
                httpx.Response(200, json={"rules": []}, headers={_RESOLVED: "2.0.0"}),
            ]
        )
        with connect_context(_BASE, context_id=_CTX, context_version="latest") as ctx:
            ctx.scheme.process("H")
            ctx.access.rules()
            ctx.access.rules()
            assert rules.call_count == 1
            clock[0] += 301.0
            ctx.scheme.process("H")
            assert route.call_count == 2
            assert ctx.resolved_version == "2.0.0"
            ctx.scheme.process("H")
            assert route.call_count == 2
            ctx.access.rules()
            assert rules.call_count == 2

    @respx.mock
    def test_disable_cache_keeps_scheme_reads_on_the_wire(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        _describe_route()
        with connect_context(
            _BASE, context_id=_CTX, context_version=_VER, disable_cache=True
        ) as ctx:
            ctx.scheme.process("H")
            ctx.scheme.process("H")
            assert route.call_count == 2

    @respx.mock
    def test_unauthorized_response_discards_cached_answers(self):
        process = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with _connect() as ctx:
            ctx.scheme.process("H")
            with pytest.raises(EzClassifyClientError):
                ctx.access.check([], {})
            ctx.scheme.process("H")
            assert process.call_count == 2

    @pytest.mark.parametrize("method", ["POST", "GET"])
    @respx.mock
    def test_the_runtime_denial_discards_cached_answers(self, method):
        # A deployment running authentication answers an unauthenticated
        # request with a 404 and exactly this body, so it refuses the caller
        # the same way a 401 does.
        process = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        denial = httpx.Response(404, json={"error": "not_found"})
        if method == "POST":
            respx.post(_ctx_url("access/check")).mock(return_value=denial)
        else:
            respx.get(_ctx_url("access/rules")).mock(return_value=denial)
        with _connect() as ctx:
            ctx.scheme.process("H")
            with pytest.raises(EzClassifyClientError) as failure:
                if method == "POST":
                    ctx.access.check([], {})
                else:
                    ctx.access.rules()
            assert failure.value.status_code == 404
            ctx.scheme.process("H")
            assert process.call_count == 2

    @pytest.mark.parametrize(
        "body",
        [
            {"error": "not_found", "detail": "no preset named banner"},
            {"error": "preset_not_found"},
            {"code": "not_found"},
        ],
    )
    @respx.mock
    def test_a_resource_not_found_keeps_cached_answers(self, body):
        process = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        respx.post(_ctx_url("scheme/apply-preset")).mock(
            return_value=httpx.Response(404, json=body)
        )
        with _connect() as ctx:
            ctx.scheme.process("H")
            with pytest.raises(EzClassifyClientError):
                ctx.scheme.apply_preset("banner")
            ctx.scheme.process("H")
            assert process.call_count == 1

    @respx.mock
    def test_guide_and_document_calls_are_not_cached(self):
        guide = respx.post(_ctx_url("guide/scan")).mock(
            return_value=httpx.Response(200, json=_envelope([]), headers=_HDR)
        )
        with _connect() as ctx:
            ctx.guide.scan("text")
            ctx.guide.scan("text")
            assert guide.call_count == 2
            assert not ctx._caches("POST", "document/audit")


class TestScheme:
    def test_named_envelope_from_dict_keeps_concrete_result_type(self):
        result = ContextSchemeProcessResult.from_dict(_envelope(_process_result()))
        assert isinstance(result, ContextSchemeProcessResult)
        assert result.result.rendered == "H"

    @respx.mock
    def test_suggest_for_categories_answers_the_map_by_category(self):
        route = respx.post(_ctx_url("scheme/suggest-for-categories")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "level": {"suggestions": [], "warnings": []},
                        "audience": {
                            "suggestions": [
                                {
                                    "conceptId": "staff",
                                    "categoryId": "audience",
                                    "label": "STAFF",
                                    "description": "Staff only",
                                    "name": "Staff",
                                    "views": {"default": "STAFF"},
                                    "group": "",
                                    "selected": False,
                                    "order": 0,
                                }
                            ],
                            "warnings": [],
                        },
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.suggest_for_categories(
            [Assertion(categoryId="level", conceptId="high")], ["level", "audience"]
        )
        assert isinstance(result, ContextSchemeSuggestForCategoriesResult)
        assert set(result.result) == {"level", "audience"}
        assert result.result["audience"].suggestions[0].label == "STAFF"
        assert json.loads(route.calls.last.request.content) == {
            "assertions": [
                {
                    "categoryId": "level",
                    "conceptId": "high",
                    "source": "parse",
                    "confidence": "certain",
                }
            ],
            "categoryIds": ["level", "audience"],
        }

    @respx.mock
    def test_suggest_for_categories_naming_none_accepts_an_empty_map(self):
        respx.post(_ctx_url("scheme/suggest-for-categories")).mock(
            return_value=httpx.Response(200, json=_envelope({}), headers=_HDR)
        )
        assert _connect().scheme.suggest_for_categories([], []).result == {}

    @pytest.mark.parametrize("disable_cache", [False, True])
    @respx.mock
    def test_suggest_for_categories_refuses_an_answer_missing_a_category(
        self, disable_cache
    ):
        route = respx.post(_ctx_url("scheme/suggest-for-categories")).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_envelope({"level": {"suggestions": [], "warnings": []}}),
                    headers=_HDR,
                ),
                httpx.Response(
                    200,
                    json=_envelope(
                        {
                            "level": {"suggestions": [], "warnings": []},
                            "audience": {"suggestions": [], "warnings": []},
                        }
                    ),
                    headers=_HDR,
                ),
            ]
        )
        _describe_route()
        with connect_context(
            _BASE, context_id=_CTX, context_version=_VER, disable_cache=disable_cache
        ) as ctx:
            with pytest.raises(MalformedResponseError, match="no result for: audience"):
                ctx.scheme.suggest_for_categories([], ["level", "audience"])
            # The malformed answer was not kept, so asking again reaches the
            # server instead of failing from memory.
            retried = ctx.scheme.suggest_for_categories([], ["level", "audience"])
            assert set(retried.result) == {"level", "audience"}
            assert route.call_count == 2

    @respx.mock
    def test_process(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    _process_result(
                        assertions=[
                            {
                                "conceptId": "L_H",
                                "categoryId": "level",
                                "confidence": "certain",
                                "source": "parse",
                            }
                        ]
                    )
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.process("H")
        assert isinstance(result, ContextSchemeProcessResult)
        assert result.result.valid and result.result.rendered == "H"
        assert len(result.result.assertions) == 1
        body = json.loads(route.calls.last.request.content)
        assert body["input"] == "H"
        assert "schemeId" not in body

    @respx.mock
    def test_process_sends_named_outputs_and_categories_and_omits_them_unset(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    _process_result(
                        renders={
                            "marking/short": {
                                "rendered": "H",
                                "assessment": _ASSESSMENT,
                            }
                        },
                        suggestionsFor={"level": {"suggestions": [], "warnings": []}},
                    )
                ),
                headers=_HDR,
            )
        )
        ctx = _connect()
        result = ctx.scheme.process(
            "H", outputs=["marking/short"], suggest_for=["level"]
        )
        body = json.loads(route.calls.last.request.content)
        assert body == {
            "input": "H",
            "outputs": ["marking/short"],
            "suggestFor": ["level"],
        }
        assert set(result.result.renders) == {"marking/short"}
        assert result.result.suggestions_for is not None
        assert set(result.result.suggestions_for) == {"level"}

        ctx.scheme.process("H")
        body = json.loads(route.calls.last.request.content)
        assert body == {"input": "H"}

    @respx.mock
    def test_process_sends_an_empty_output_list_rather_than_dropping_it(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        _connect().scheme.process("H", outputs=[])
        # An empty list is an answer, not an absence: it reaches the server.
        assert json.loads(route.calls.last.request.content) == {
            "input": "H",
            "outputs": [],
        }

    @respx.mock
    def test_process_settles_typed_text_with_the_facts_already_chosen(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        _connect().scheme.process(
            "", assertions=[Assertion(categoryId="level", conceptId="H")]
        )
        assert json.loads(route.calls.last.request.content) == {
            "input": "",
            "assertions": [
                {
                    "categoryId": "level",
                    "conceptId": "H",
                    "confidence": "certain",
                    "source": "parse",
                }
            ],
        }

    @respx.mock
    def test_process_reports_verdicts_as_the_server_sent_them(self):
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_process_result(valid=True, inputWasValid=False)),
                headers=_HDR,
            )
        )
        result = _connect().scheme.process("h").result
        assert result.valid is True
        assert result.input_was_valid is False

    @respx.mock
    def test_process_sends_parts_and_omits_it_unset(self):
        route = respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        ctx = _connect()
        ctx.scheme.process("H//A", parts=["A"])
        body = json.loads(route.calls.last.request.content)
        assert body["parts"] == ["A"]

        ctx.scheme.process("H//A")
        body = json.loads(route.calls.last.request.content)
        assert "parts" not in body

    @respx.mock
    def test_validate(self):
        route = respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    _validate_result(
                        valid=False,
                        inputWasValid=False,
                        errors=[
                            {
                                "constraintId": "_unmatched_token",
                                "message": "bad",
                                "didYouMean": ["HIGH"],
                            }
                        ],
                        recognition={
                            "status": "partial",
                            "inputFormat": "marking/banner",
                            "role": "whole",
                            "surface": "marking",
                            "unmatched": [],
                        },
                    )
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.validate("H")
        assert isinstance(result, ContextSchemeValidateResult)
        assert result.result.valid is False and len(result.result.errors) == 1
        assert result.result.errors[0].did_you_mean == ["HIGH"]
        assert result.result.recognition is not None
        assert result.result.recognition["inputFormat"] == "marking/banner"
        assert result.result.recognition["role"] == "whole"
        assert json.loads(route.calls.last.request.content) == {"input": "H"}

    @respx.mock
    def test_validate_takes_facts_as_stated_without_text(self):
        route = respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result()), headers=_HDR
            )
        )
        _connect().scheme.validate(
            assertions=[Assertion(categoryId="level", conceptId="H")],
            context={"role": "whole"},
        )
        # The route refuses a body that carries both, so facts go out alone.
        assert json.loads(route.calls.last.request.content) == {
            "assertions": [
                {
                    "categoryId": "level",
                    "conceptId": "H",
                    "confidence": "certain",
                    "source": "parse",
                }
            ],
            "context": {"role": "whole"},
        }

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"marking": "H", "assertions": [Assertion(categoryId="l", conceptId="H")]},
        ],
        ids=["neither", "both"],
    )
    @respx.mock
    def test_validate_needs_exactly_one_of_text_or_facts(self, arguments):
        route = respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result()), headers=_HDR
            )
        )
        with pytest.raises(ValueError, match="exactly one of marking or assertions"):
            _connect().scheme.validate(**arguments)
        assert not route.called

    @respx.mock
    def test_validate_answers_no_authoring_members(self):
        # A server that sent the authoring answers on validate would not put
        # them on the reader's result.
        respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_validate_result(proposedFixes=[], renders={})),
                headers=_HDR,
            )
        )
        result = _connect().scheme.validate("H").result
        assert not hasattr(result, "proposed_fixes")
        assert not hasattr(result, "renders")

    @respx.mock
    def test_explain(self):
        route = respx.post(_ctx_url("scheme/explain")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    _trace(
                        entries=[
                            {
                                "stage": "infer",
                                "action": "add",
                                "detail": "Added STAFF.",
                                "ruleId": "high-needs-staff",
                            }
                        ]
                    )
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.explain(
            "H",
            assertions=[Assertion(categoryId="level", conceptId="H")],
            context={"role": "whole"},
            output_format="marking/banner",
        )
        assert isinstance(result, ContextSchemeExplainResult)
        assert result.result.entries[0].rule_id == "high-needs-staff"
        assert result.result.rendered == "H"
        body = json.loads(route.calls.last.request.content)
        assert body["input"] == "H"
        assert body["outputFormat"] == "marking/banner"
        assert body["context"] == {"role": "whole"}
        assert body["assertions"][0]["conceptId"] == "H"

    @respx.mock
    def test_validate_sends_parts_and_omits_it_unset(self):
        route = respx.post(_ctx_url("scheme/validate")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_process_result()), headers=_HDR
            )
        )
        ctx = _connect()
        ctx.scheme.validate("H//A", parts=["A"])
        body = json.loads(route.calls.last.request.content)
        assert body["parts"] == ["A"]

        ctx.scheme.validate("H//A")
        body = json.loads(route.calls.last.request.content)
        assert "parts" not in body

    @respx.mock
    def test_suggest(self):
        respx.post(_ctx_url("scheme/suggest")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "suggestions": [
                            {
                                "conceptId": "L_H",
                                "label": "H",
                                "categoryId": "level",
                                "description": "high",
                                "name": "High",
                                "group": "",
                                "selected": False,
                                "order": 0,
                                "views": {"default": "H"},
                            }
                        ],
                        "warnings": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.suggest("L")
        assert isinstance(result, ContextSchemeSuggestResult)
        assert len(result.result.suggestions) == 1
        assert result.result.suggestions[0].concept_id == "L_H"

    @respx.mock
    def test_aggregate(self):
        route = respx.post(_ctx_url("scheme/aggregate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_aggregate_result()),
                headers=_HDR,
            )
        )
        result = _connect().scheme.aggregate(["L", "H"])
        assert isinstance(result, ContextSchemeAggregateResult)
        assert result.result.rendered == "H"
        assert json.loads(route.calls.last.request.content)["inputs"] == ["L", "H"]

    @respx.mock
    def test_aggregate_assertions(self):
        route = respx.post(_ctx_url("scheme/aggregate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_aggregate_result(rendered="HIGH")),
                headers=_HDR,
            )
        )
        result = _connect().scheme.aggregate_assertions(
            [
                [Assertion(conceptId="LOW", categoryId="level")],
                [
                    Assertion(conceptId="HIGH", categoryId="level"),
                    Assertion(conceptId="ORIG", categoryId="origin", value="ABCXYZ"),
                ],
            ],
            output_format="full",
            surface="portion",
        )
        assert isinstance(result, ContextSchemeAggregateResult)
        assert result.result.rendered == "HIGH"
        body = json.loads(route.calls.last.request.content)
        # The assertion-set path is mutually exclusive with `inputs`.
        assert "inputs" not in body
        assert body["outputFormat"] == "full"
        assert body["surface"] == "portion"
        assert "format" not in body
        assert body["assertionSets"][1][1]["value"] == "ABCXYZ"

    @respx.mock
    def test_scan(self):
        respx.post(_ctx_url("scheme/scan")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "results": [
                            {
                                "marking": "H",
                                "start": 5,
                                "end": 6,
                                "type": "marking/banner",
                                "wrapped": False,
                                "role": "whole",
                                "result": _validate_result(
                                    recognition={
                                        "status": "complete",
                                        "inputFormat": "marking/banner",
                                        "role": "whole",
                                        "surface": "marking",
                                        "unmatched": [],
                                    }
                                ),
                            }
                        ],
                        "unread": [],
                        "limits": {"status": "complete", "regionsFound": 1},
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.scan("doc H")
        assert (
            isinstance(result, ContextSchemeScanResult)
            and len(result.result.results) == 1
            and result.result.results[0].marking == "H"
            # The whole point of the object: an empty list from a scan that
            # stopped early is not the same answer as a clean document.
            and result.result.limits.status == "complete"
        )
        match = result.result.results[0]
        # A region carries what validate answers for it, so the view it was
        # read as and its role are on the region without a second call.
        assert match.type == "marking/banner"
        assert match.result.recognition is not None
        assert match.result.recognition["inputFormat"] == match.type
        assert not hasattr(match.result, "proposed_fixes")

    @respx.mock
    def test_render_returns_named_envelope(self):
        assessment = {
            "emitted": [{"conceptId": "L_H", "categoryId": "level", "value": "HIGH"}],
            "omitted": [],
            "collapsed": [],
            "conflicts": [],
            "unrepresentable": [],
        }
        route = respx.post(_ctx_url("scheme/render")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"result": "LEVEL-HIGH", "assessment": assessment}),
                headers=_HDR,
            )
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
            )
        ]
        rendered = _connect().scheme.render(
            a, output_format="banner", preservation="full"
        )
        assert isinstance(rendered, ContextSchemeRenderResult)
        assert rendered.result.result == "LEVEL-HIGH"
        assert rendered.result.assessment == assessment
        body = json.loads(route.calls.last.request.content)
        assert body["assertions"][0]["conceptId"] == "L_H"
        assert body["outputFormat"] == "banner"
        assert body["preservation"] == "full"
        assert "schemeId" not in body

    @respx.mock
    def test_normalize_unwraps_result(self):
        respx.post(_ctx_url("scheme/normalize")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"result": "LEVEL-HIGH"}),
                headers=_HDR,
            )
        )
        normalized = _connect().scheme.normalize("high")
        assert isinstance(normalized, ContextSchemeNormalizeResult)
        assert normalized.result.result == "LEVEL-HIGH"

    @respx.mock
    def test_check_coverage(self):
        respx.post(_ctx_url("scheme/check-coverage")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "covered": False,
                        "missing": [],
                        "missingLabels": ["HIGH"],
                        "excess": [],
                        "excessLabels": [],
                        "rendered": "HIGH",
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.check_coverage(["HIGH"], "HIGH/CTRL-A")
        assert (
            isinstance(result, ContextSchemeCoverageResult)
            and result.result.covered is False
            and result.result.missing_labels == ["HIGH"]
            and result.result.excess_labels == []
        )

    @respx.mock
    def test_describe_concept_uses_get_with_params(self):
        route = respx.get(_ctx_url("scheme/describe-concept")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "conceptId": "L_H",
                        "categoryId": "level",
                        "name": "High",
                        "lines": ["High"],
                        "definition": "the high level",
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.describe_concept("L_H", "level")
        assert (
            isinstance(result, ContextSchemeConceptDescriptionResult)
            and result.result.name == "High"
            and result.result.lines == ["High"]
        )
        req = route.calls.last.request
        assert req.method == "GET"
        assert req.url.params["conceptId"] == "L_H"
        assert req.url.params["categoryId"] == "level"

    @respx.mock
    def test_render_rejects_a_response_missing_required_fields(self):
        respx.post(_ctx_url("scheme/render")).mock(
            return_value=httpx.Response(
                200, json={"rendered": "LEVEL-HIGH"}, headers=_HDR
            )
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
            )
        ]
        with pytest.raises(MalformedResponseError) as raised:
            _connect().scheme.render(a)
        assert raised.value.path == "$.resolution"

    @respx.mock
    def test_render_rejects_non_object_response(self):
        respx.post(_ctx_url("scheme/render")).mock(
            return_value=httpx.Response(200, json=42, headers=_HDR)
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
            )
        ]
        with pytest.raises(MalformedResponseError) as raised:
            _connect().scheme.render(a)
        assert raised.value.path == "$"

    @respx.mock
    def test_render_assertion_value_forwarded(self):
        # Assertion with non-None value; exercises the _assertion_to_wire value branch.
        route = respx.post(_ctx_url("scheme/render")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "result": "H",
                        "assessment": {
                            "emitted": [],
                            "omitted": [],
                            "collapsed": [],
                            "conflicts": [],
                            "unrepresentable": [],
                        },
                    }
                ),
                headers=_HDR,
            )
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
                value="H",
            )
        ]
        _connect().scheme.render(a)
        body = json.loads(route.calls.last.request.content)
        assert body["assertions"][0]["value"] == "H"

    @respx.mock
    def test_render_full_preservation_refusal_stays_typed(self):
        respx.post(_ctx_url("scheme/render")).mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": "render would lose facts",
                    "code": "RENDER_NOT_PRESERVING",
                    "detail": "omitted authority AUTH-X=A&B",
                },
                headers=_HDR,
            )
        )
        assertion = Assertion(
            conceptId="AUTH-X",
            categoryId="authority",
            confidence="certain",
            source="parse",
            value="A&B",
        )
        with pytest.raises(EzClassifyClientError) as caught:
            _connect().scheme.render([assertion], preservation="full")
        assert caught.value.status_code == 400
        assert caught.value.code == "RENDER_NOT_PRESERVING"
        assert caught.value.detail == "omitted authority AUTH-X=A&B"

    @respx.mock
    def test_normalize_rejects_string_response(self):
        respx.post(_ctx_url("scheme/normalize")).mock(
            return_value=httpx.Response(200, json="LEVEL-HIGH", headers=_HDR)
        )
        with pytest.raises(MalformedResponseError, match="expected a JSON object"):
            _connect().scheme.normalize("high")

    @respx.mock
    def test_normalize_rejects_non_object_response(self):
        respx.post(_ctx_url("scheme/normalize")).mock(
            return_value=httpx.Response(200, json=99, headers=_HDR)
        )
        with pytest.raises(MalformedResponseError, match="expected a JSON object"):
            _connect().scheme.normalize("99")

    @respx.mock
    def test_describe_concept_with_view_param(self):
        route = respx.get(_ctx_url("scheme/describe-concept")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "conceptId": "L_H",
                        "categoryId": "level",
                        "name": "High",
                        "lines": [],
                        "definition": "",
                    }
                ),
                headers=_HDR,
            )
        )
        _connect().scheme.describe_concept("L_H", "level", view="default")
        assert route.calls.last.request.url.params["view"] == "default"

    @respx.mock
    def test_diff(self):
        respx.post(_ctx_url("scheme/diff")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "added": [
                            {
                                "conceptId": "A",
                                "categoryId": "c",
                                "confidence": "certain",
                                "source": "parse",
                            }
                        ],
                        "removed": [],
                        "common": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.diff("A", "B")
        assert isinstance(result, ContextSchemeDiffResult)
        assert len(result.result.added) == 1

    @respx.mock
    def test_filter_concepts(self):
        respx.post(_ctx_url("scheme/filter-concepts")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "visibleIds": ["a", "b"],
                        "categoryCounts": {"level": {"visible": 2, "total": 5}},
                        "total": {"visible": 2, "total": 9},
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.filter_concepts("hi")
        assert isinstance(result, ContextSchemeFilterConceptsResult)
        assert result.result.visible_ids == ["a", "b"]
        assert (
            result.result.category_counts["level"].visible == 2
            and result.result.category_counts["level"].total == 5
        )
        assert result.result.total.total == 9

    @respx.mock
    def test_notices(self):
        respx.post(_ctx_url("scheme/notices")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    [
                        {
                            "conceptId": "INT",
                            "conceptName": "Internal Handling",
                            "type": "handling",
                            "text": "controlled",
                            "required": True,
                        }
                    ]
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.notices([])
        assert (
            isinstance(result, ContextSchemeNoticesResult)
            and len(result.result) == 1
            and result.result[0].required
            and result.result[0].type == "handling"
        )

    @respx.mock
    def test_process_carries_the_collected_notices(self):
        """A processed marking answers with its notices, so no second call is needed."""
        notice = {
            "conceptId": "INT",
            "conceptName": "Internal Handling",
            "type": "handling",
            "text": "controlled",
            "required": True,
        }
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_process_result(notices=[notice])),
                headers=_HDR,
            )
        )
        result = _connect().scheme.process("H")
        assert len(result.result.notices) == 1
        assert result.result.notices[0].concept_id == "INT"

    @respx.mock
    def test_aggregate_carries_the_collected_notices(self):
        """The aggregate result collects notices the same way, on the same field."""
        respx.post(_ctx_url("scheme/aggregate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    _aggregate_result(
                        notices=[
                            {
                                "conceptId": "INT",
                                "conceptName": "Internal Handling",
                                "type": "handling",
                                "text": "controlled",
                                "required": False,
                            }
                        ]
                    )
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.aggregate(["L", "H"])
        assert len(result.result.notices) == 1
        assert result.result.notices[0].required is False

    @respx.mock
    def test_view(self):
        respx.post(_ctx_url("scheme/view")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "id": "s",
                        "name": "Scheme",
                        "description": "d",
                        "categories": [
                            {
                                "id": "level",
                                "label": "Level",
                                "items": [_concept_view(id="H")],
                            }
                        ],
                        "uncategorized": [],
                        "vocabulary": {
                            "concept": {"singular": "item", "plural": "items"}
                        },
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().scheme.view()
        assert isinstance(result, ContextSchemeViewResult)
        assert result.result.name == "Scheme"
        assert (
            len(result.result.categories) == 1
            and result.result.categories[0].label == "Level"
            and len(result.result.categories[0].items) == 1
        )
        assert result.result.vocabulary["concept"].singular == "item"
        assert result.result.vocabulary["concept"].plural == "items"


_SUMMARY_BODY = {
    "id": "levels",
    "version": "1.0.0",
    "name": "Levels",
    "description": "d",
    "roleAware": False,
    "referenceSurfaceLabel": {"singular": "Handbook", "plural": "Handbooks"},
    # `embeddedMarking` is omitted, which is how the contract says a scheme
    # declares that inline marking is off.
    "defaultRenderFormat": "banner",
}

_GRAMMAR_BODY = {"caseSensitive": False, "stripWhitespace": True}


class TestSchemeResources:
    """The eight context-scoped scheme resource routes.

    Seven answer with the bare resource; only apply-preset is enveloped,
    because only apply-preset runs a marking through the scheme.
    """

    @respx.mock
    def test_summary_reads_the_bare_resource(self):
        route = respx.get(_ctx_url("scheme")).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "levels",
                    "version": "1.0.0",
                    "name": "Levels",
                    "description": "d",
                    "roleAware": False,
                    "referenceSurfaceLabel": {
                        "singular": "Handbook",
                        "plural": "Handbooks",
                    },
                    "embeddedMarking": [
                        {"pattern": "\\(([^)]+)\\)", "template": "({marking}) "}
                    ],
                    "defaultRenderFormat": "banner",
                    "defaultPartRenderFormat": "portion",
                    "defaultWholeRenderFormat": "banner",
                },
                headers=_HDR,
            )
        )
        summary = _connect().scheme.summary()
        assert route.calls.last.request.method == "GET"
        assert route.calls.last.request.url.path == f"/v1/ctx/{_CTX}/{_VER}/scheme"
        assert "scheme" not in route.calls.last.request.url.params
        # Flat, not enveloped: no "result" wrapper to unwrap.
        assert summary.id == "levels"
        assert summary.default_render_format == "banner"
        assert summary.default_part_render_format == "portion"
        assert summary.default_whole_render_format == "banner"
        assert summary.reference_surface_label.singular == "Handbook"
        # A list of embedded marking styles.
        assert summary.embedded_marking is not None
        assert summary.embedded_marking[0]["template"] == "({marking}) "

    @respx.mock
    def test_concepts(self):
        route = respx.get(_ctx_url("scheme/concepts")).mock(
            return_value=httpx.Response(200, json=[_full_concept_view()], headers=_HDR)
        )
        concepts = _connect().scheme.concepts()
        assert (
            route.calls.last.request.url.path
            == f"/v1/ctx/{_CTX}/{_VER}/scheme/concepts"
        )
        assert route.calls.last.request.url.query == b""
        assert isinstance(concepts[0], ConceptView)
        assert len(concepts) == 1 and concepts[0].name == "High"
        assert concepts[0].views == {"default": "High"}
        assert concepts[0].definition == "The high level."
        assert concepts[0].guidance == "Use sparingly."
        assert concepts[0].rules_referencing == ["H needs STAFF."]
        assert concepts[0].text_input is not None
        assert concepts[0].text_input["label"] == "Name"

    @respx.mock
    def test_scheme_rows_parse_with_the_optional_fields_omitted(self):
        """These fields are optional in the contract, so a row may omit them.

        A scheme that declares no ranks, no scopes, no grouping members and no
        deprecations sends none of those keys, and the row must still validate.
        """
        respx.get(_ctx_url("scheme/concepts")).mock(
            return_value=httpx.Response(200, json=[_concept_view()], headers=_HDR)
        )
        respx.get(_ctx_url("scheme/categories")).mock(
            return_value=httpx.Response(200, json=[_category_view()], headers=_HDR)
        )
        respx.get(_ctx_url("scheme/formats")).mock(
            return_value=httpx.Response(200, json=[_format_view()], headers=_HDR)
        )
        client = _connect()

        concept = client.scheme.concepts()[0]
        assert concept.rank is None
        assert concept.members is None and concept.scopes is None
        assert concept.deprecated is None and concept.definition is None
        assert concept.text_input is None

        category = client.scheme.categories()[0]
        assert category.required is None and category.single is None
        assert category.scopes is None and category.position is None
        assert category.hierarchy_root is None

        assert client.scheme.formats()[0].category_separators is None

    @respx.mock
    def test_categories(self):
        route = respx.get(_ctx_url("scheme/categories")).mock(
            return_value=httpx.Response(200, json=[_full_category_view()], headers=_HDR)
        )
        categories = _connect().scheme.categories()
        assert (
            route.calls.last.request.url.path
            == f"/v1/ctx/{_CTX}/{_VER}/scheme/categories"
        )
        assert isinstance(categories[0], CategoryView)
        assert categories[0].label == "Level" and categories[0].required is True
        assert categories[0].position == 1
        # `rollup` is untyped on the wire; a bare string must survive.
        assert categories[0].rollup == "max"

    @respx.mock
    def test_formats(self):
        route = respx.get(_ctx_url("scheme/formats")).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "banner",
                        "surface": "whole",
                        "categoryOrder": ["level"],
                        "separator": "/",
                        "mode": "block",
                        "categorySeparators": {"control": "//"},
                    },
                    {
                        "id": "sensitivity/short",
                        "surface": "sensitivity",
                        "outputView": "short",
                        "defaultFor": ["part"],
                        "role": "part",
                        "mode": "inline",
                        "separator": " // ",
                        "categoryOrder": ["level", "sharing"],
                    },
                ],
                headers=_HDR,
            )
        )
        formats = _connect().scheme.formats()
        assert (
            route.calls.last.request.url.path == f"/v1/ctx/{_CTX}/{_VER}/scheme/formats"
        )
        assert formats[0].mode == "block"
        assert formats[0].category_separators == {"control": "//"}
        # A format with no view carries none of the view's members.
        assert formats[0].output_view is None
        assert formats[0].default_for is None and formats[0].role is None
        view = formats[1]
        assert view.id == "sensitivity/short"
        assert view.output_view == "short"
        assert view.default_for == ["part"]
        assert view.role == "part"

    @respx.mock
    def test_grammar(self):
        route = respx.get(_ctx_url("scheme/grammar")).mock(
            return_value=httpx.Response(
                200,
                json={
                    "caseSensitive": False,
                    "stripWhitespace": True,
                },
                headers=_HDR,
            )
        )
        grammar = _connect().scheme.grammar()
        assert (
            route.calls.last.request.url.path == f"/v1/ctx/{_CTX}/{_VER}/scheme/grammar"
        )
        assert grammar.case_sensitive is False

    @respx.mock
    def test_scopes(self):
        respx.get(_ctx_url("scheme/scopes")).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "doc", "label": "Document"},
                    {"id": "portion", "label": "Portion"},
                ],
                headers=_HDR,
            )
        )
        scopes = _connect().scheme.scopes()
        # An array, not a map: the declaration order is the order a selector
        # offers them in, and a JSON object does not carry order.
        assert all(isinstance(scope, SchemeScope) for scope in scopes)
        assert [scope.id for scope in scopes] == ["doc", "portion"]
        assert scopes[0].label == "Document"

    @respx.mock
    def test_a_scheme_that_declares_no_scopes_answers_an_empty_list(self):
        respx.get(_ctx_url("scheme/scopes")).mock(
            return_value=httpx.Response(200, json=[], headers=_HDR)
        )
        assert _connect().scheme.scopes() == []

    @respx.mock
    def test_label_presets(self):
        route = respx.get(_ctx_url("scheme/label-presets")).mock(
            return_value=httpx.Response(
                200,
                json=[_label_preset_view()],
                headers=_HDR,
            )
        )
        presets = _connect().scheme.label_presets()
        assert (
            route.calls.last.request.url.path
            == f"/v1/ctx/{_CTX}/{_VER}/scheme/label-presets"
        )
        # Presets belong to the primary scheme: no selector rides along.
        assert route.calls.last.request.url.query == b""
        assert isinstance(presets[0], LabelPresetView)
        assert presets[0].id == "default-label" and presets[0].scope == "doc"

    @respx.mock
    def test_empty_preset_list_is_returned_as_is(self):
        respx.get(_ctx_url("scheme/label-presets")).mock(
            return_value=httpx.Response(200, json=[], headers=_HDR)
        )
        assert _connect().scheme.label_presets() == []

    @respx.mock
    def test_apply_preset_is_enveloped(self):
        route = respx.post(_ctx_url("scheme/apply-preset")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result(rendered="HIGH")), headers=_HDR
            )
        )
        result = _connect().scheme.apply_preset("default-label")
        assert route.calls.last.request.method == "POST"
        assert (
            route.calls.last.request.url.path
            == f"/v1/ctx/{_CTX}/{_VER}/scheme/apply-preset"
        )
        assert json.loads(route.calls.last.request.content) == {
            "presetId": "default-label"
        }
        assert route.calls.last.request.url.query == b""
        # Unlike the seven reads, this one comes back in the standard context
        # operation envelope, so the marking is under .result.
        assert isinstance(result, ContextSchemeValidateResult)
        assert result.result.rendered == "HIGH"
        assert result.resolution.resolved_version == "9.9.9"

    @respx.mock
    def test_apply_preset_forwards_output_format(self):
        route = respx.post(_ctx_url("scheme/apply-preset")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result()), headers=_HDR
            )
        )
        _connect().scheme.apply_preset("default-label", output_format="portion")
        assert json.loads(route.calls.last.request.content) == {
            "presetId": "default-label",
            "outputFormat": "portion",
        }

    @respx.mock
    def test_apply_preset_rejects_blank_preset_id(self):
        route = respx.post(_ctx_url("scheme/apply-preset")).mock(
            return_value=httpx.Response(
                200, json=_envelope(_validate_result()), headers=_HDR
            )
        )
        with pytest.raises(ValueError):
            _connect().scheme.apply_preset("  ")
        assert not route.called

    @pytest.mark.parametrize(
        ("op", "resource", "body"),
        [
            ("summary", "scheme", _SUMMARY_BODY),
            ("concepts", "scheme/concepts", []),
            ("categories", "scheme/categories", []),
            ("formats", "scheme/formats", []),
            ("grammar", "scheme/grammar", _GRAMMAR_BODY),
            ("scopes", "scheme/scopes", []),
        ],
    )
    @respx.mock
    def test_scheme_parameter_reaches_a_crosswalk_side(self, op, resource, body):
        """The six reads that take ?scheme= use it to read a crosswalk's sides."""
        route = respx.get(_ctx_url(resource)).mock(
            return_value=httpx.Response(200, json=body, headers=_HDR)
        )
        getattr(_connect().scheme, op)(scheme="target-side")
        assert route.calls.last.request.url.params["scheme"] == "target-side"

    @pytest.mark.parametrize(
        ("op", "resource"),
        [
            ("summary", "scheme"),
            ("concepts", "scheme/concepts"),
        ],
    )
    @respx.mock
    def test_blank_scheme_key_rejected_before_the_request(self, op, resource):
        route = respx.get(_ctx_url(resource)).mock(
            return_value=httpx.Response(200, json=[], headers=_HDR)
        )
        with pytest.raises(ValueError):
            getattr(_connect().scheme, op)(scheme="   ")
        assert not route.called

    @respx.mock
    def test_array_resource_rejects_an_object_body(self):
        respx.get(_ctx_url("scheme/concepts")).mock(
            return_value=httpx.Response(200, json={"concepts": []}, headers=_HDR)
        )
        with pytest.raises(MalformedResponseError, match="expected a JSON array"):
            _connect().scheme.concepts()

    @respx.mock
    def test_array_resource_rejects_non_object_items(self):
        respx.get(_ctx_url("scheme/formats")).mock(
            return_value=httpx.Response(200, json=["banner"], headers=_HDR)
        )
        with pytest.raises(MalformedResponseError) as raised:
            _connect().scheme.formats()
        assert raised.value.path == "$[0]"

    @respx.mock
    def test_object_resource_rejects_an_array_body(self):
        respx.get(_ctx_url("scheme/grammar")).mock(
            return_value=httpx.Response(200, json=[], headers=_HDR)
        )
        with pytest.raises(MalformedResponseError, match="expected a JSON object"):
            _connect().scheme.grammar()

    @respx.mock
    def test_resource_read_surfaces_a_404(self):
        respx.get(_ctx_url("scheme/concepts")).mock(
            return_value=httpx.Response(404, json={"error": "no such scheme key"})
        )
        with pytest.raises(EzClassifyClientError) as failure:
            _connect().scheme.concepts(scheme="not-here")
        assert failure.value.status_code == 404

    @respx.mock
    def test_resource_read_refreshes_the_resolved_version(self):
        respx.get(_ctx_url("scheme")).mock(
            return_value=httpx.Response(
                200,
                json=_SUMMARY_BODY,
                headers={"X-EzClassify-Resolved-Version": "3.1.4"},
            )
        )
        ctx = _connect()
        ctx.scheme.summary()
        assert ctx.resolved_version == "3.1.4"


class TestGuide:
    @respx.mock
    def test_scan(self):
        route = respx.post(_ctx_url("guide/scan")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    [
                        {
                            "rule": {
                                "id": "r1",
                                "name": "Rule",
                                "keywords": ["secret"],
                                "outcome": {"rendered": "H"},
                            },
                            "matchedKeywords": ["secret"],
                            "spans": [{"keyword": "secret", "start": 0, "end": 6}],
                            "guideId": "g1",
                        }
                    ]
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.scan("secret", "g1")
        assert (
            isinstance(result, ContextGuideScanResult)
            and len(result.result) == 1
            and result.result[0].rule.id == "r1"
        )
        assert "schemeId" not in json.loads(route.calls.last.request.content)

    @respx.mock
    def test_evaluate(self):
        route = respx.post(_ctx_url("guide/evaluate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "aggregatedMarking": "H",
                        "selectedRules": [
                            {
                                "id": "r1",
                                "name": "Rule",
                                "outcome": {"rendered": "H"},
                            }
                        ],
                        "activeComputedRules": [],
                        "effectiveMarkings": ["H"],
                        "guideId": "g1",
                        "breakdown": [],
                        "contributingBreakdown": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.evaluate("g1", "r1")
        assert isinstance(result, ContextGuideEvaluationResult)
        assert result.result.aggregated_marking == "H"
        body = json.loads(route.calls.last.request.content)
        assert body["guideId"] == "g1" and "schemeId" not in body

    @respx.mock
    def test_evaluate_many(self):
        route = respx.post(_ctx_url("guide/evaluate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "aggregatedMarking": "H",
                        "selectedRules": [],
                        "activeComputedRules": [],
                        "effectiveMarkings": ["H"],
                        "breakdown": [],
                        "contributingBreakdown": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.evaluate_many("r2")
        assert result.result.aggregated_marking == "H"
        assert json.loads(route.calls.last.request.content) == {
            "allGuides": True,
            "selectedRuleIds": ["r2"],
        }

    @respx.mock
    def test_filter_rules(self):
        respx.post(_ctx_url("guide/filter-rules")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "visibleIds": ["r1"],
                        "categoryCounts": {},
                        "total": {"visible": 1, "total": 3},
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.filter_rules("sec")
        assert isinstance(result, ContextGuideFilterRulesResult)
        assert result.result.visible_ids == ["r1"]

    @respx.mock
    def test_filter_rules_with_guide_id(self):
        route = respx.post(_ctx_url("guide/filter-rules")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "visibleIds": [],
                        "categoryCounts": {},
                        "total": {"visible": 0, "total": 0},
                    }
                ),
                headers=_HDR,
            )
        )
        _connect().guide.filter_rules("sec", guide_id="g1")
        assert json.loads(route.calls.last.request.content)["guideId"] == "g1"

    @respx.mock
    def test_describe_rule(self):
        respx.post(_ctx_url("guide/describe-rule")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "rule": _rule("guide", "g1"),
                        "guide": _artifact("guide", "g1"),
                        "name": "Rule",
                        "outcomeText": "marks H",
                        "isComputed": False,
                        "dependsOn": [],
                        "overrides": [],
                        "lines": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.describe_rule("r1")
        assert (
            isinstance(result, ContextGuideRuleDescriptionResult)
            and result.result.outcome_text == "marks H"
            and result.result.is_computed is False
        )

    @respx.mock
    def test_describe_rule_with_guide_id(self):
        route = respx.post(_ctx_url("guide/describe-rule")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "rule": _rule("guide", "g1"),
                        "guide": _artifact("guide", "g1"),
                        "name": "Rule",
                        "outcomeText": "marks H",
                        "isComputed": False,
                        "dependsOn": [],
                        "overrides": [],
                        "lines": [],
                    }
                ),
                headers=_HDR,
            )
        )
        _connect().guide.describe_rule("r1", guide_id="g1")
        assert json.loads(route.calls.last.request.content)["guideId"] == "g1"

    @respx.mock
    def test_view(self):
        respx.post(_ctx_url("guide/view")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "id": "g1",
                        "name": "Guide",
                        "description": "",
                        "categories": [],
                        "uncategorized": [_guide_rule_view("r1")],
                        "vocabulary": {
                            "rule": {"singular": "entry", "plural": "entries"}
                        },
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().guide.view("g1")
        assert (
            isinstance(result, ContextGuideViewResult)
            and result.result.name == "Guide"
            and len(result.result.uncategorized) == 1
        )
        assert result.result.vocabulary["rule"].singular == "entry"
        assert result.result.vocabulary["rule"].plural == "entries"


class TestAccess:
    @respx.mock
    def test_check_omits_scheme_id_uses_user_attributes(self):
        route = respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "granted": True,
                        "rules": [_access_result()],
                        "warnings": [],
                    }
                ),
                headers=_HDR,
            )
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
            )
        ]
        result = _connect().access.check(a, {"clearance": "HIGH"})
        assert (
            isinstance(result, ContextAccessDecisionResult)
            and result.result.granted
            and len(result.result.rules) == 1
        )
        body = json.loads(route.calls.last.request.content)
        assert "userAttributes" in body and "assertions" in body
        assert "schemeId" not in body and "scheme_id" not in body

    @respx.mock
    def test_check_preserves_all_populated_assertion_fields(self):
        # A data assertion's expiry and provenance must reach the server on the
        # ctx surface; dropping expiresAt would let an expired marking be
        # evaluated as live. The ctx serializer must match the client serializer.
        route = respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"granted": False, "rules": [], "warnings": []}),
                headers=_HDR,
            )
        )
        a = [
            Assertion(
                conceptId="L_H",
                categoryId="level",
                confidence="certain",
                source="parse",
                expiresAt="2020-01-01T00:00:00Z",
                sourceRule="r-42",
                metadata={"k": "v"},
                provenance={
                    "providerId": "idp-1",
                    "attribution": {"name": "IdP", "license": "internal"},
                    "reproducibility": "best-effort",
                },
                value="CAP",
            )
        ]
        _connect().access.check(a, {"clearance": "HIGH"})
        wire = json.loads(route.calls.last.request.content)["assertions"][0]
        assert wire["expiresAt"] == "2020-01-01T00:00:00Z"
        assert wire["sourceRule"] == "r-42"
        assert wire["metadata"] == {"k": "v"}
        assert wire["provenance"]["providerId"] == "idp-1"
        assert wire["value"] == "CAP"

    @respx.mock
    def test_check_by_marking(self):
        route = respx.post(_ctx_url("access/check")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope({"granted": False, "rules": [], "warnings": []}),
                headers=_HDR,
            )
        )
        result = _connect().access.check_by_marking("HIGH/I", {"clearance": "team-a"})
        assert result.result.granted is False
        body = json.loads(route.calls.last.request.content)
        assert body["marking"] == "HIGH/I" and "schemeId" not in body

    @respx.mock
    def test_describe_requirements(self):
        respx.post(_ctx_url("access/describe-requirements")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "marking": "HIGH/I",
                        "assertions": [],
                        "assertionDisplays": [],
                        "access": _artifact("access", "ap"),
                        "scheme": _artifact("scheme", "s"),
                        "appliedRules": [_rule("access", "ap")],
                        "rules": [],
                        "combinedRequirementText": "internal only",
                        "combinedAttributesNeeded": ["team"],
                        "lines": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().access.describe_requirements("HIGH/I")
        assert isinstance(result, ContextAccessRequirementsResult)
        assert result.result.combined_attributes_needed == ["team"]

    @respx.mock
    def test_describe_rule(self):
        respx.post(_ctx_url("access/describe-rule")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    {
                        "rule": _rule("access", "ap"),
                        "access": _artifact("access", "ap"),
                        "scheme": _artifact("scheme", "s"),
                        "name": "Internal",
                        "requirementText": "internal only",
                        "attributesNeeded": ["team"],
                        "dependsOn": [],
                        "overrides": [],
                        "lines": [],
                    }
                ),
                headers=_HDR,
            )
        )
        result = _connect().access.describe_rule("r1")
        assert (
            isinstance(result, ContextAccessRuleDescriptionResult)
            and result.result.name == "Internal"
            and result.result.attributes_needed == ["team"]
        )

    @respx.mock
    def test_rules(self):
        rule = {
            "rule": _rule("access", "ap"),
            "access": _artifact("access", "ap"),
            "scheme": _artifact("scheme", "s"),
            "name": "Internal",
            "requirementText": "internal only",
            "attributesNeeded": ["team"],
            "dependsOn": [],
            "overrides": [],
            "lines": [],
        }
        route = respx.get(_ctx_url("access/rules")).mock(
            return_value=httpx.Response(200, json={"rules": [rule]}, headers=_HDR)
        )
        result = _connect().access.rules()
        assert isinstance(result, CtxAccessRulesResponseBody)
        assert result.rules[0].name == "Internal"
        assert route.called


class TestCrosswalk:
    @respx.mock
    def test_translate_marking(self):
        route = respx.post(_ctx_url("crosswalk/translate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_translation()),
                headers=_HDR,
            )
        )
        result = _connect().crosswalk.translate(
            "state-to-district", marking="LEVEL-HIGH"
        )
        assert isinstance(result, ContextCrosswalkTranslationResult)
        assert result.result["status"] == "completed"
        assert json.loads(route.calls.last.request.content) == {
            "crosswalkId": "state-to-district",
            "marking": "LEVEL-HIGH",
        }

    @respx.mock
    def test_translate_assertions(self):
        route = respx.post(_ctx_url("crosswalk/translate")).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(_translation()),
                headers=_HDR,
            )
        )
        result = _connect().crosswalk.translate(
            "state-to-district",
            assertions=[Assertion(categoryId="level", conceptId="high")],
        )
        assert result.result["status"] == "completed"
        assert "assertions" in json.loads(route.calls.last.request.content)

    @respx.mock
    def test_translate_requires_exactly_one_source(self):
        ctx = _connect()
        # Input validation happens before transport, so no request is needed.
        with pytest.raises(ValueError, match="exactly one"):
            ctx.crosswalk.translate("x")


def _audit_validation(
    rendered: str, *, inputWasValid: bool = True, role: str = "whole"
) -> dict:
    """How an audit judged one marking: facts, recognition and both verdicts."""
    return {
        "assertions": [
            {
                "categoryId": "level",
                "conceptId": rendered.split("/")[0],
                "confidence": "certain",
                "source": "parse",
            }
        ],
        "recognition": {
            "status": "complete",
            "role": role,
            "surface": "marking",
            "unmatched": [],
        },
        "valid": True,
        "inputWasValid": inputWasValid,
        "errors": [],
        "proposedFixes": [],
        "appliedFixes": [],
        "rendered": rendered,
    }


class TestDocument:
    @respx.mock
    def test_audit(self):
        route = respx.post(_ctx_url("document/audit")).mock(
            return_value=httpx.Response(
                200,
                json={
                    "resolution": {
                        "contextId": _CTX,
                        "resolvedVersion": "9.9.9",
                        "artifacts": [],
                        "sources": [],
                    },
                    "operationLimitations": [],
                    "result": {
                        "whole": "HIGH/I",
                        "wholes": [
                            {
                                "marking": "HIGH/I",
                                "start": 0,
                                "end": 6,
                                "offsetEncoding": "utf-8-bytes",
                            }
                        ],
                        "wholeValidation": _audit_validation("HIGH/I"),
                        "parts": [
                            {
                                "marking": "MED",
                                "text": "para",
                                "start": 10,
                                "end": 14,
                                "offsetEncoding": "utf-8-bytes",
                                "scopeId": "part:1",
                                "validation": _audit_validation(
                                    "MED", inputWasValid=False, role="part"
                                ),
                            }
                        ],
                        "wholeCoversParts": {
                            "covered": True,
                            "missing": [],
                            "missingLabels": [],
                            "excess": [],
                            "excessLabels": [],
                            "rendered": "HIGH/I",
                        },
                        "unmarkedSpans": [
                            {
                                "start": 20,
                                "end": 25,
                                "text": "extra",
                                "offsetEncoding": "utf-8-bytes",
                            }
                        ],
                        "proceduralFlags": ["unmarked-content"],
                        "overallVerdict": "mixed",
                        "vocabulary": None,
                        "documentDigest": "sha256:test",
                        "guideAssessment": None,
                        "markingRequirements": {"whole": False, "part": False},
                        "limitations": [],
                    },
                },
                headers=_HDR,
            )
        )
        result = _connect().document.audit("a doc")
        assert isinstance(result, ContextDocumentAuditResult)
        report = result.result
        assert report.whole == "HIGH/I" and len(report.wholes) == 1
        assert len(report.parts) == 1 and report.parts[0].scope_id == "part:1"
        # Each audited marking carries its facts and how it was read, so a
        # caller rolls up or checks access without reading it a second time.
        part = report.parts[0].validation
        assert part.valid is True and part.input_was_valid is False
        assert part.assertions[0].concept_id == "MED"
        assert part.recognition["role"] == "part"
        assert report.whole_validation is not None
        assert report.whole_validation.input_was_valid is True
        assert report.whole_covers_parts is not None
        assert len(report.unmarked_spans) == 1 and report.overall_verdict == "mixed"
        assert json.loads(route.calls.last.request.content)["text"] == "a doc"


class TestErrors:
    @respx.mock
    def test_document_error_preserves_public_code_detail_and_message(self):
        _describe_route()
        respx.post(_ctx_url("document/audit")).mock(
            return_value=httpx.Response(
                409,
                json={
                    "error": "Guide determination is stale for the submitted document.",
                    "code": "INVALID_INPUT",
                    "detail": "stale-guide-determination",
                },
            )
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(EzClassifyClientError) as exc_info:
            ctx.document.audit("HIGH")
        assert exc_info.value.code == "INVALID_INPUT"
        assert exc_info.value.detail == "stale-guide-determination"
        assert "Guide determination is stale" in str(exc_info.value)

    @respx.mock
    def test_op_propagates_server_error(self):
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(404, text="context not found")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(
            EzClassifyClientError, match="REST API error 404"
        ) as exc_info:
            ctx.scheme.process("H")
        assert exc_info.value.status_code == 404

    @respx.mock
    def test_op_5xx_raises(self):
        # Complement to test_op_propagates_server_error; confirms 5xx is also surfaced.
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(500, text="internal server error")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(
            EzClassifyClientError, match="REST API error 500"
        ) as exc_info:
            ctx.scheme.process("H")
        assert exc_info.value.status_code == 500

    @respx.mock
    def test_connect_server_error_raises(self):
        # connect_context runs a describe probe; if that fails, it should raise.
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            return_value=httpx.Response(404, text="context not found")
        )
        with pytest.raises(
            EzClassifyClientError, match="REST API error 404"
        ) as exc_info:
            connect_context(_BASE, context_id=_CTX, context_version=_VER)
        assert exc_info.value.status_code == 404

    @respx.mock
    def test_connect_failure_closes_transport(self):
        # When the resolve probe raises, the handle is unreachable, so the httpx
        # client opened by connect_context must be closed before re-raising.
        respx.get(f"{_BASE}/v1/ctx/{_CTX}/{_VER}").mock(
            return_value=httpx.Response(404, text="context not found")
        )
        created: list[httpx.Client] = []
        original_init = httpx.Client.__init__

        def tracking_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created.append(self)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.Client, "__init__", tracking_init)
            with pytest.raises(EzClassifyClientError):
                connect_context(_BASE, context_id=_CTX, context_version=_VER)
        assert len(created) == 1
        assert created[0].is_closed

    @respx.mock
    def test_op_malformed_body_raises(self):
        # A 200 carrying something other than JSON is a malformed response, and
        # it surfaces as the documented client error rather than a decoder error.
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(200, content=b"not-valid-json", headers=_HDR)
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(MalformedResponseError, match="non-JSON body") as exc_info:
            ctx.scheme.process("H")
        assert exc_info.value.status_code == 200
        assert exc_info.value.path == "$"
        assert "scheme/process" in str(exc_info.value)

    @respx.mock
    def test_op_non_object_body_raises(self):
        # A JSON array where the operation contract promises an object is
        # reported against the operation, not as a model validation error.
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(200, json=[], headers=_HDR)
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(
            MalformedResponseError, match="expected a JSON object"
        ) as exc_info:
            ctx.scheme.process("H")
        assert "scheme/process" in str(exc_info.value)

    def test_blank_context_id_rejected(self):
        with pytest.raises(ValueError, match="context_id must not be blank"):
            connect_context(_BASE, context_id="  ", context_version=_VER)

    def test_blank_context_version_rejected(self):
        with pytest.raises(
            ValueError, match="context_version must not be only whitespace"
        ):
            connect_context(_BASE, context_id=_CTX, context_version="  ")

    @respx.mock
    def test_op_connection_error_raises(self):
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(EzClassifyClientError, match="Connection error") as exc_info:
            ctx.scheme.process("H")
        assert exc_info.value.status_code == 0

    @respx.mock
    def test_get_op_http_error_raises(self):
        # describe_concept uses _get; verify that path surfaces errors the same way.
        _describe_route()
        respx.get(_ctx_url("scheme/describe-concept")).mock(
            return_value=httpx.Response(404, text="concept not found")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(
            EzClassifyClientError, match="REST API error 404"
        ) as exc_info:
            ctx.scheme.describe_concept("UNKNOWN", "level")
        assert exc_info.value.status_code == 404

    @respx.mock
    def test_get_op_connection_error_raises(self):
        # _get path must surface RequestError as EzClassifyClientError with status_code=0.
        _describe_route()
        respx.get(_ctx_url("scheme/describe-concept")).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(EzClassifyClientError, match="Connection error") as exc_info:
            ctx.scheme.describe_concept("L_H", "level")
        assert exc_info.value.status_code == 0

    @respx.mock
    def test_ctx_non_2xx_raises_typed_exception_not_runtime_error(self):
        # The context client raises EzClassifyClientError (typed), not
        # RuntimeError or a generic Exception, on any non-2xx response.
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(503, text="service unavailable")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(EzClassifyClientError) as exc_info:
            ctx.scheme.process("X")
        assert isinstance(exc_info.value, EzClassifyClientError)
        assert not isinstance(exc_info.value, RuntimeError)

    @respx.mock
    def test_ctx_404_status_code_distinguishable_from_connection_failure(self):
        # status_code is the discriminant: HTTP 404 → 404, connection failure → 0.
        # Callers branch on exc.status_code without catching a second exception type.
        _describe_route()
        respx.post(_ctx_url("scheme/process")).mock(
            return_value=httpx.Response(404, text="not found")
        )
        ctx = connect_context(_BASE, context_id=_CTX, context_version=_VER)
        with pytest.raises(EzClassifyClientError) as exc_info:
            ctx.scheme.process("X")
        assert exc_info.value.status_code == 404
        assert exc_info.value.status_code != 0
