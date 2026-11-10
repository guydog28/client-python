"""Document assessment façade and wire-fidelity contracts."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import ValidationError

from ezclassify_rest_client import EzClassifyClientError, connect_context
from ezclassify_rest_contract import (
    ContextDocumentAuditResult,
    ContextAccessDecisionResult,
    GuideDeterminationInput,
)

BASE = "http://localhost:9999"
ROOT = f"{BASE}/v1/ctx/demo/1.0.0"
HEADERS = {"X-EzClassify-Resolved-Version": "1.0.0"}

# The Context description connecting reads; not the answer under test.
_DESCRIPTION = {
    "id": "demo",
    "version": "1.0.0",
    "scheme": {"id": "s", "version": "1.0.0", "resolvedVersion": "1.0.0"},
    "schemes": [{"selector": "s", "id": "s", "version": "1.0.0", "roles": []}],
}


def _resolution() -> dict:
    return {
        "contextId": "demo",
        "requestedVersion": "1.0.0",
        "resolvedVersion": "1.0.0",
        "artifacts": [{"kind": "scheme", "id": "scheme", "version": "1.0.0"}],
        "sources": [
            {
                "providerId": "catalog",
                "attribution": {"name": "Catalog", "license": "Apache-2.0"},
                "reproducibility": "reproducible",
                "snapshotId": "sha256:abc",
                "locator": "memory://catalog",
            }
        ],
    }


def _audit() -> dict:
    return {
        "whole": None,
        "wholes": [],
        "wholeValidation": None,
        "parts": [],
        "wholeCoversParts": None,
        "unmarkedSpans": [{"start": 0, "end": 3, "offsetEncoding": "utf-8-bytes"}],
        "proceduralFlags": ["unmarked-text-present"],
        "overallVerdict": "procedural-gap",
        "vocabulary": None,
        "documentDigest": "sha256:document",
        "markingRequirements": {"whole": False, "part": False},
        "guideAssessment": {
            "status": "pending-determination",
            "nominationCount": 1,
            "unresolvedCount": 1,
            "acceptedCount": 0,
            "rejectedCount": 0,
            "evidenceSpanCount": 1,
            "unitCoverage": [],
            "determinedRequiredWhole": None,
            "projectedRequiredWhole": None,
            "determinedWholeCoverage": None,
            "projectedWholeCoverage": None,
        },
        "limitations": [],
    }


def _projection() -> dict:
    return {
        "profile": "summary",
        "detailsComplete": False,
        "omittedFields": ["/result/guideAssessment/evaluation"],
        "counts": {
            "nominations": 1,
            "evidenceSpans": 1,
            "guideUnits": 1,
            "accessRuleResults": 0,
            "contentRequirements": 0,
            "contextRequirements": 0,
        },
    }


def _connect():
    respx.get(ROOT).mock(
        return_value=httpx.Response(200, json=_DESCRIPTION, headers=HEADERS)
    )
    return connect_context(BASE, context_id="demo", context_version="1.0.0")


@respx.mock
def test_audit_returns_typed_envelope_and_preserves_omissions() -> None:
    route = respx.post(f"{ROOT}/document/audit").mock(
        return_value=httpx.Response(
            200,
            json={
                "resolution": _resolution(),
                "result": _audit(),
                "operationLimitations": [],
                "responseProjection": _projection(),
            },
            headers=HEADERS,
        )
    )
    with _connect() as ctx:
        result = ctx.document.audit(
            "é critical 😀",
            guide_determinations={"findings": [], "manualSelections": []},
            response_profile="summary",
        )

    assert isinstance(result, ContextDocumentAuditResult)
    assert result.resolution.sources[0].snapshot_id == "sha256:abc"
    assert result.result.document_digest == "sha256:document"
    assert result.result.unmarked_spans[0].text is None
    assert result.result.unmarked_spans[0].offset_encoding == "utf-8-bytes"
    assert result.response_projection is not None
    assert result.response_projection.counts.evidence_spans == 1
    body = json.loads(route.calls.last.request.content)
    assert body["responseProfile"] == "summary"
    assert body["guideDeterminations"]["manualSelections"] == []


@respx.mock
def test_structured_stale_error_is_available_without_message_parsing() -> None:
    respx.post(f"{ROOT}/document/audit").mock(
        return_value=httpx.Response(
            409,
            json={
                "code": "INVALID_INPUT",
                "detail": "stale-guide-determination",
                "error": "The determination is stale.",
            },
        )
    )
    with _connect() as ctx, pytest.raises(EzClassifyClientError) as caught:
        ctx.document.audit("record")

    assert caught.value.status_code == 409
    assert caught.value.code == "INVALID_INPUT"
    assert caught.value.detail == "stale-guide-determination"
    assert caught.value.payload is not None
    assert str(caught.value).endswith("The determination is stale.")


def _rule() -> dict:
    return {
        "artifact": {
            "kind": "access",
            "id": "policy",
            "version": "1.0.0",
            "digest": "sha256:policy",
        },
        "ruleId": "allow-team",
        "ruleDigest": "sha256:rule",
        "source": {
            "providerId": "catalog",
            "reproducibility": "reproducible",
            "snapshotId": "sha256:source",
        },
    }


def _evidence() -> dict:
    return {
        "start": 3,
        "end": 9,
        "offsetEncoding": "utf-8-bytes",
        "rule": _rule(),
        "matched": "secret",
    }


def test_full_nested_document_models_are_lossless_and_strict() -> None:
    audit = _audit()
    audit["guideAssessment"]["evaluation"] = {
        "documentDigest": "sha256:document",
        "nominations": [
            {
                "findingId": "finding:1",
                "documentDigest": "sha256:document",
                "origin": "lexical",
                "rule": _rule(),
                "evidence": [_evidence()],
                "proposedAssertions": [{"categoryId": "level", "conceptId": "HIGH"}],
                "rationale": "Keyword match.",
            }
        ],
        "determinations": [],
        "manualSelections": [],
        "unresolvedFindingIds": ["finding:1"],
        "acceptedFindingIds": [],
        "rejectedFindingIds": [],
        "supportCatalog": [
            {
                "supportId": "support:1",
                "assertion": {"categoryId": "level", "conceptId": "HIGH"},
                "rules": [_rule()],
                "evidence": [_evidence()],
                "factReferences": [
                    {"kind": "projected-finding", "factId": "finding:1"}
                ],
            }
        ],
        "units": [
            {
                "scopeId": "document",
                "start": 0,
                "end": 9,
                "offsetEncoding": "utf-8-bytes",
                "findingIds": ["finding:1"],
                "determined": None,
                "projected": None,
            }
        ],
        "limitations": [],
    }
    decision_payload = {
        "granted": False,
        "rules": [
            {
                "ruleIndex": 0,
                "name": "Allow team",
                "granted": False,
                "skipped": False,
                "activation": {
                    "matched": True,
                    "assertions": [{"categoryId": "level", "conceptId": "HIGH"}],
                    "contextPaths": ["mission.team"],
                },
                "comparisons": [
                    {
                        "left": {"source": "subject", "path": "team"},
                        "operator": "equals",
                        "right": {"source": "context", "path": "mission.team"},
                        "matched": False,
                        "missing": ["blue"],
                    }
                ],
                "rule": _rule(),
                "reason": "Team mismatch.",
            }
        ],
        "warnings": [],
        "provenance": {
            "providerId": "catalog",
            "attribution": {
                "name": "Catalog",
                "license": "Apache-2.0",
                "licenseUrl": "https://example.test/license",
                "citation": "Catalog release 1.",
            },
            "reproducibility": "reproducible",
            "snapshotId": "sha256:source",
        },
    }
    result = ContextDocumentAuditResult.from_dict(
        {
            "resolution": _resolution(),
            "result": audit,
            "operationLimitations": [],
        }
    )

    nomination = result.result.guide_assessment.evaluation.nominations[0]
    decision = ContextAccessDecisionResult.from_dict(
        {
            "resolution": _resolution(),
            "result": decision_payload,
            "operationLimitations": [],
        }
    ).result
    assert nomination.evidence[0].rule.rule_digest == "sha256:rule"
    assert decision.rules[0].comparisons[0].missing == ["blue"]
    assert decision.provenance.attribution.license_url == "https://example.test/license"
    assert decision.provenance.attribution.citation == "Catalog release 1."

    malformed = _audit()
    del malformed["documentDigest"]
    with pytest.raises(ValidationError):
        ContextDocumentAuditResult.from_dict(
            {
                "resolution": _resolution(),
                "result": malformed,
                "operationLimitations": [],
            }
        )

    malformed = _audit()
    malformed["unmarkedSpans"] = [
        {"start": 0, "end": 1, "offsetEncoding": "utf-16-code-units"}
    ]
    with pytest.raises(ValidationError):
        ContextDocumentAuditResult.from_dict(
            {
                "resolution": _resolution(),
                "result": malformed,
                "operationLimitations": [],
            }
        )


@respx.mock
def test_typed_guide_determinations_serialize_to_canonical_wire_shape() -> None:
    route = respx.post(f"{ROOT}/document/audit").mock(
        return_value=httpx.Response(
            200,
            json={
                "resolution": _resolution(),
                "result": _audit(),
                "operationLimitations": [],
            },
            headers=HEADERS,
        )
    )
    determinations = GuideDeterminationInput.model_validate(
        {
            "findings": [
                {
                    "findingId": "finding:1",
                    "documentDigest": "sha256:document",
                    "decision": "rejected",
                    "reason": "False positive.",
                    "proposalOrigin": "analyst-authored",
                }
            ],
            "manualSelections": [],
        }
    )
    with _connect() as ctx:
        ctx.document.audit("record", guide_determinations=determinations)

    body = json.loads(route.calls.last.request.content)
    assert body["guideDeterminations"]["findings"][0]["findingId"] == "finding:1"
    assert body["guideDeterminations"]["manualSelections"] == []
