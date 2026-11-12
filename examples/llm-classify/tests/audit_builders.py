"""Builders for typed audit results shared by the llm-classify unit tests."""

from __future__ import annotations

from typing import Any

from ezclassify_rest_client import (
    AggregateResult,
    AuditPart,
    CoverageReport,
    DocumentAuditReport,
    MarkingValidation,
    Notice,
)

_RECOGNITION: dict[str, Any] = {"status": "complete", "unmatched": []}


def validation(
    rendered: str, valid: bool = True, errors: list[dict[str, Any]] | None = None
) -> MarkingValidation:
    """Build a MarkingValidation for *rendered* with the given wire errors."""
    return MarkingValidation.model_validate(
        {
            "assertions": [],
            "recognition": _RECOGNITION,
            "valid": valid,
            "inputWasValid": valid,
            "errors": errors or [],
            "proposedFixes": [],
            "appliedFixes": [],
            "rendered": rendered,
        }
    )


def part(
    marking: str,
    start: int = 0,
    *,
    valid: bool = True,
    rendered: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> AuditPart:
    """Build an authored part marking and the way the audit judged it."""
    return AuditPart.model_validate(
        {
            "marking": marking,
            "start": start,
            "end": start + len(marking),
            "offsetEncoding": "utf-8-bytes",
            "scopeId": "portion",
            "validation": validation(
                marking if rendered is None else rendered, valid, errors
            ).model_dump(by_alias=True),
        }
    )


def coverage(
    covered: bool,
    *,
    missing_labels: list[str] | None = None,
    excess_labels: list[str] | None = None,
    refusals: list[dict[str, Any]] | None = None,
) -> CoverageReport:
    """Build the report of whether the authored whole covers the parts."""
    return CoverageReport.model_validate(
        {
            "covered": covered,
            "excess": [],
            "excessLabels": excess_labels or [],
            "missing": [],
            "missingLabels": missing_labels or [],
            "refusals": refusals,
            "rendered": "",
        }
    )


def audit_report(
    parts: list[AuditPart],
    *,
    whole: str | None = None,
    whole_validation: MarkingValidation | None = None,
    whole_covers_parts: CoverageReport | None = None,
    overall_verdict: str = "pass",
    procedural_flags: list[str] | None = None,
) -> DocumentAuditReport:
    """Build a document audit report in the shape the wire carries."""
    return DocumentAuditReport.model_validate(
        {
            "markingRequirements": {"whole": True, "part": True},
            "whole": whole,
            "wholes": [],
            "wholeValidation": (
                None
                if whole_validation is None
                else whole_validation.model_dump(by_alias=True)
            ),
            "parts": [p.model_dump(by_alias=True) for p in parts],
            "wholeCoversParts": (
                None
                if whole_covers_parts is None
                else whole_covers_parts.model_dump(by_alias=True)
            ),
            "unmarkedSpans": [],
            "proceduralFlags": procedural_flags or [],
            "overallVerdict": overall_verdict,
            "vocabulary": None,
            "documentDigest": "sha256-test",
            "guideAssessment": None,
            "limitations": [],
        }
    )


def aggregate(
    rendered: str, valid: bool = True, notices: list[Notice] | None = None
) -> AggregateResult:
    """Build an aggregate result."""
    return AggregateResult(
        rendered=rendered,
        valid=valid,
        assertions=[],
        errors=[],
        warnings=[],
        applied_fixes=[],
        proposed_fixes=[],
        notices=notices or [],
    )
