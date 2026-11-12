"""Unit tests for the llm-classify example app.

Tests use unittest.mock in place of the EzClassifyClient HTTP calls, so no
live server is needed. The test suite verifies that ``classify()`` drives the
expected MCP tool-use sequence, audit → aggregate over the valid parts, and
that the report shows what the audit and aggregate answered.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from audit_builders import aggregate, audit_report, coverage, part, validation
from classifier import ClassifyResult, classify, print_report
from client import EzClassifyClient
from ezclassify_rest_client import AggregateResult, DocumentAuditReport, Notice

SIMPLE_TEXT = "Document with marking HIGH and LOW."

AGGREGATE_HIGH = aggregate("HIGH")
INTERNAL_NOTICE = Notice(
    conceptId="INT",
    conceptName="Internal Handling",
    type="handling",
    text="Route through the program office.",
    required=True,
)


def make_client(
    report: DocumentAuditReport, aggregate_result: AggregateResult | None = None
) -> MagicMock:
    """Build a mock client with canned responses."""
    client = MagicMock(spec=EzClassifyClient)
    client.audit.return_value = report
    client.aggregate.return_value = aggregate_result or aggregate("", False)
    return client


def render_report(capsys: pytest.CaptureFixture[str], result: ClassifyResult) -> str:
    print_report(result)
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def test_audit_called_once_with_full_text() -> None:
    client = make_client(audit_report([part("HIGH"), part("LOW")]), AGGREGATE_HIGH)
    classify(SIMPLE_TEXT, client, verbose=False)
    client.audit.assert_called_once_with(SIMPLE_TEXT)


def test_aggregate_called_once_with_the_valid_parts_in_document_order() -> None:
    client = make_client(audit_report([part("LOW"), part("HIGH")]), AGGREGATE_HIGH)
    result = classify(SIMPLE_TEXT, client, verbose=False)
    client.aggregate.assert_called_once_with(["LOW", "HIGH"])
    assert result.aggregate is AGGREGATE_HIGH


def test_aggregate_takes_the_settled_marking_not_the_authored_spelling() -> None:
    report = audit_report([part("high", rendered="HIGH")])
    client = make_client(report, AGGREGATE_HIGH)
    classify(SIMPLE_TEXT, client, verbose=False)
    client.aggregate.assert_called_once_with(["HIGH"])


def test_repeated_part_markings_are_aggregated_once() -> None:
    report = audit_report([part("HIGH", 0), part("HIGH", 20), part("LOW", 40)])
    client = make_client(report, AGGREGATE_HIGH)
    classify(SIMPLE_TEXT, client, verbose=False)
    client.aggregate.assert_called_once_with(["HIGH", "LOW"])


def test_parts_that_failed_validation_are_excluded_from_aggregate() -> None:
    report = audit_report([part("HIGH", 0), part("BOGUS", 10, valid=False)])
    client = make_client(report, AGGREGATE_HIGH)
    result = classify(SIMPLE_TEXT, client, verbose=False)
    client.aggregate.assert_called_once_with(["HIGH"])
    assert [p.marking for p in result.audit.parts] == ["HIGH", "BOGUS"]


def test_single_part_still_calls_aggregate() -> None:
    """Even with one part, aggregate must be called; the MCP contract requires it."""
    client = make_client(audit_report([part("HIGH")]), AGGREGATE_HIGH)
    classify(SIMPLE_TEXT, client, verbose=False)
    client.aggregate.assert_called_once_with(["HIGH"])


def test_document_without_parts_skips_aggregate() -> None:
    client = make_client(audit_report([]))
    result = classify("No markings here.", client, verbose=False)
    client.aggregate.assert_not_called()
    assert result.aggregate is None


def test_document_with_only_invalid_parts_skips_aggregate() -> None:
    client = make_client(audit_report([part("BOGUS", valid=False)]))
    result = classify("BOGUS text", client, verbose=False)
    client.aggregate.assert_not_called()
    assert result.aggregate is None


# ---------------------------------------------------------------------------
# Tool-call printing
# ---------------------------------------------------------------------------


def test_verbose_mode_prints_each_tool_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report([part("HIGH"), part("BOGUS", 10, valid=False)], whole="HIGH")
    classify(SIMPLE_TEXT, make_client(report, AGGREGATE_HIGH), verbose=True)
    out = capsys.readouterr().out
    assert "[tool: audit_document_markings]" in out
    assert "found 2 part marking(s): ['HIGH', 'BOGUS']" in out
    assert "failed validation: ['BOGUS']" in out
    assert "[tool: aggregate_markings]" in out
    assert "inputs: ['HIGH']" in out
    assert "overall: 'HIGH'" in out


def test_quiet_mode_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    client = make_client(audit_report([part("HIGH")]), AGGREGATE_HIGH)
    classify(SIMPLE_TEXT, client, verbose=False)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_lists_every_part_marking_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report([part("LOW"), part("MED", 10)], whole="MED")
    out = render_report(capsys, ClassifyResult(report, aggregate("MED")))
    assert "Markings Found (2)\n   LOW\n   MED\n" in out
    assert "Validation Issues\n   None" in out


def test_report_explains_why_a_part_failed_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bogus = part(
        "BOGUS",
        valid=False,
        errors=[
            {"constraintId": "unknown", "message": "BOGUS is not a recognized marking"},
        ],
    )
    out = render_report(
        capsys, ClassifyResult(audit_report([bogus, part("LOW", 10)]), None)
    )
    assert "'BOGUS': failed validation\n     BOGUS is not a recognized marking" in out


def test_report_shows_authored_overall_that_covers_the_parts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report(
        [part("LOW")],
        whole="HIGH",
        whole_validation=validation("HIGH"),
        whole_covers_parts=coverage(True),
    )
    out = render_report(capsys, ClassifyResult(report, AGGREGATE_HIGH))
    assert "Authored Overall Marking\n   HIGH\n   Covers the parts: yes" in out
    assert "Document verdict: pass" in out


def test_report_says_what_an_authored_overall_is_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report(
        [part("HIGH")],
        whole="LOW",
        whole_covers_parts=coverage(
            False, missing_labels=["HIGH"], excess_labels=["PUBLIC"]
        ),
        overall_verdict="inadequate-coverage",
    )
    out = render_report(capsys, ClassifyResult(report, AGGREGATE_HIGH))
    assert "Covers the parts: no" in out
    assert "Missing: HIGH" in out
    assert "Not supported by the parts: PUBLIC" in out
    assert "Document verdict: inadequate-coverage" in out


def test_report_gives_the_reasons_a_coverage_check_was_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report(
        [part("HIGH")],
        whole="LOW",
        whole_covers_parts=coverage(
            False,
            refusals=[{"constraintId": "rollup", "message": "rollup was refused"}],
        ),
    )
    out = render_report(capsys, ClassifyResult(report, AGGREGATE_HIGH))
    assert "Covers the parts: no\n     rollup was refused" in out


def test_report_gives_the_reasons_the_authored_overall_failed_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    whole = validation(
        "",
        valid=False,
        errors=[{"constraintId": "unknown", "message": "overall is not recognized"}],
    )
    report = audit_report([part("LOW")], whole="WHAT", whole_validation=whole)
    out = render_report(capsys, ClassifyResult(report, aggregate("LOW")))
    assert "   WHAT\n   Failed validation:\n     overall is not recognized" in out
    assert "Covers the parts: not assessed" in out


def test_report_says_when_the_document_has_no_authored_overall(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = audit_report(
        [part("LOW")],
        procedural_flags=["missing-overall-marking"],
        overall_verdict="procedural-gap",
    )
    out = render_report(capsys, ClassifyResult(report, aggregate("LOW")))
    assert "Authored Overall Marking\n   (none found)" in out
    assert "Procedural finding: missing-overall-marking" in out
    assert "Document verdict: procedural-gap" in out


def test_report_shows_the_overall_marking_the_parts_require(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = render_report(
        capsys, ClassifyResult(audit_report([part("HIGH")]), AGGREGATE_HIGH)
    )
    assert "Overall Marking Required by the Parts\n   HIGH\n" in out


def test_report_says_when_no_part_could_be_combined(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = render_report(capsys, ClassifyResult(audit_report([]), None))
    assert "Markings Found (0)\n   (none)" in out
    assert "(no valid part markings to combine)" in out
    assert "Handling Notices\n   None" in out


def test_report_reads_notices_off_the_aggregate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The report shows the aggregate's own notices, with no notices call."""
    aggregated = aggregate("HIGH", notices=[INTERNAL_NOTICE])
    out = render_report(
        capsys, ClassifyResult(audit_report([part("HIGH")]), aggregated)
    )
    assert "Handling Notices" in out
    assert "Internal Handling: Route through the program office." in out
    assert "acknowledgment required" in out


def test_report_says_none_when_the_aggregate_carries_no_notices(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = render_report(
        capsys, ClassifyResult(audit_report([part("HIGH")]), AGGREGATE_HIGH)
    )
    assert "Handling Notices\n   None" in out
