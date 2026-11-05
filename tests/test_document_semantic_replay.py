"""Replay the canonical document-assessment semantic corpus through Python types."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from ezclassify_rest_client.client import _api_error
from ezclassify_contract import (
    ContextAccessRequirementsResult,
    ContextDocumentAuditResult,
)

_SEMANTIC_ROOT = Path(__file__).parents[1] / "vendor" / "spec" / "semantic" / "v1"
_CONTRACT = json.loads(
    (_SEMANTIC_ROOT / "document-assessment.contract.json").read_text()
)
_RECORDINGS = json.loads((_SEMANTIC_ROOT / "fixtures" / "recordings.json").read_text())[
    "cases"
]
_REQUESTS = json.loads((_SEMANTIC_ROOT / "fixtures" / "requests.json").read_text())
_CONTEXT = json.loads((_SEMANTIC_ROOT / "fixtures" / "context.json").read_text())
_CASES = {case["requestId"]: case for case in _CONTRACT["cases"]}
_MISSING = object()


def _resolve_path(value: Any, path: str) -> Any:
    if "[*]" in path:
        prefix, suffix = path.split("[*]", 1)
        collection = _resolve_path(value, prefix)
        if not isinstance(collection, list):
            return _MISSING
        remainder = suffix.removeprefix(".")
        matches = [_resolve_path(item, remainder) for item in collection]
        return [match for match in matches if match is not _MISSING]
    current = value
    for name, index in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
        if name:
            if not isinstance(current, dict) or name not in current:
                return _MISSING
            current = current[name]
        else:
            if not isinstance(current, list) or int(index) >= len(current):
                return _MISSING
            current = current[int(index)]
    return current


def _assert_semantic_clause(output: dict[str, Any], assertion: dict[str, Any]) -> None:
    actual = _resolve_path(output, assertion["path"])
    operator = assertion["operator"]
    expected = assertion.get("value")
    if operator == "equals":
        assert actual == expected
    elif operator == "present":
        assert actual is not _MISSING
        if "[*]" in assertion["path"]:
            assert actual
    elif operator == "absent":
        assert actual is _MISSING
    elif operator == "contains":
        assert actual is not _MISSING and expected in actual
    elif operator == "minItems":
        assert actual is not _MISSING and len(actual) >= expected
    else:  # pragma: no cover - the vendored schema closes this enum
        raise AssertionError(f"Unsupported semantic assertion operator: {operator}")


def _success_model(operation: str):
    if operation == "documentAccessRequirements":
        return ContextAccessRequirementsResult
    return ContextDocumentAuditResult


@pytest.mark.parametrize("case_id", sorted(_CASES))
def test_canonical_document_semantic_case(case_id: str) -> None:
    """Every required case survives typed replay and satisfies its semantic clauses."""
    case = _CASES[case_id]
    recording = _RECORDINGS[case_id]
    output = recording["output"]

    assert case["required"] is True
    assert case_id in _REQUESTS
    for assertion in case["assertions"]:
        _assert_semantic_clause(output, assertion)

    if "error" in output:
        local_error = output["error"]
        public_error = {
            "error": local_error["message"],
            "code": local_error["code"],
            "detail": local_error["detail"],
        }
        status = (
            422
            if local_error["code"] == "NO_ACCESS_POLICY"
            else 409
            if local_error["detail"]
            in {"stale-guide-determination", "stale-manual-selection"}
            else 400
        )
        error = _api_error(httpx.Response(status, json=public_error))
        assert error.code == local_error["code"]
        assert error.detail == local_error["detail"]
        assert error.payload == public_error
        assert str(error) == f"REST API error {status}: {local_error['message']}"
        return

    model_type = _success_model(case["operation"])
    typed = model_type.model_validate(output)
    replayed = typed.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert replayed == output


def test_semantic_corpus_is_complete() -> None:
    """Every ordered stable case identity names exactly one request and recording."""
    numbers = [case["number"] for case in _CONTRACT["cases"]]
    assert numbers, "the semantic contract declares no cases"
    assert all(number > 0 for number in numbers)
    assert numbers == sorted(set(numbers))
    assert [case["requestId"] for case in _CONTRACT["cases"]] == [
        f"case-{number:02d}" for number in numbers
    ]
    assert set(_RECORDINGS) == set(_CASES)
    assert set(_REQUESTS) == set(_CASES)


def _scheme_identity(request: dict[str, Any]) -> tuple[str, str]:
    """The Context a request runs against, read from the published variant map.

    The base fixtures apply unless the request names a ``fixtureVariant``, whose
    scheme fixture then replaces the base one. The Context's identity is the one
    that scheme fixture declares.
    """
    scheme_fixture = _CONTEXT["schemeFixture"]
    variant_name = request.get("fixtureVariant")
    if variant_name is not None:
        variant = _CONTEXT["variants"].get(variant_name)
        assert variant is not None, f"undeclared fixture variant {variant_name}"
        scheme_fixture = variant.get("schemeFixture", scheme_fixture)
    fixture = (_SEMANTIC_ROOT / "fixtures" / scheme_fixture).resolve()
    scheme = json.loads(fixture.read_text())["scheme"]
    return scheme["id"], scheme["version"]


@pytest.mark.parametrize(
    "case_id",
    sorted(
        case_id for case_id, request in _REQUESTS.items() if "fixtureVariant" in request
    ),
)
def test_variant_case_was_recorded_against_its_mapped_context(case_id: str) -> None:
    """A variant case's recording names the Context the variant map gives it."""
    context_id, _version = _scheme_identity(_REQUESTS[case_id])
    resolution = _RECORDINGS[case_id]["output"].get("resolution")
    if resolution is None:
        # A refusal has no resolved Context; pin its error contract instead.
        assert _CASES[case_id]["semanticId"] == "no-access-policy"
        assert _RECORDINGS[case_id]["output"]["error"]["code"] == "NO_ACCESS_POLICY"
        return
    assert resolution["contextId"] == context_id
