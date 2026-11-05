"""Document classification workflow that mirrors the MCP tool-use sequence.

The classifier drives two EzClassify calls in sequence, the same calls an LLM
agent makes when using the ``@ezclassify/mcp`` MCP server:

    audit_document_markings → find the overall marking and every part marking
                              in the document, and judge each one
    aggregate_markings      → compute the overall marking the valid parts
                              require

The audit reads markings someone else wrote, so it judges them the way
validate does and also checks whether the authored overall marking covers the
parts. The aggregate then says what overall marking those parts require, which
the report sets beside the one the author wrote. The aggregate result carries
its collected notices, so the report reads them straight off it instead of
calling the notices operation afterwards.

Each step is printed to stdout so the caller can see the tool-call sequence
as it unfolds, making this a CLI-friendly demonstration of the MCP workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ezclassify_contract import (
    AggregateResult,
    AuditPart,
    DocumentAuditReport,
    ValidationError,
)


class ClassifyClient(Protocol):
    """Protocol satisfied by any backend that supports audit / aggregate."""

    def audit(self, text: str) -> DocumentAuditReport: ...

    def aggregate(self, markings: list[str]) -> AggregateResult: ...


@dataclass
class ClassifyResult:
    """Complete classification result for one document.

    ``aggregate`` is ``None`` when the audit found no valid part marking to
    roll up, because aggregate has nothing to combine.
    """

    audit: DocumentAuditReport
    aggregate: AggregateResult | None


def valid_parts(audit: DocumentAuditReport) -> list[AuditPart]:
    """Return the parts the audit judged valid, in document order."""
    return [part for part in audit.parts if part.validation.valid]


def invalid_parts(audit: DocumentAuditReport) -> list[AuditPart]:
    """Return the parts the audit judged not valid, in document order."""
    return [part for part in audit.parts if not part.validation.valid]


def classify(
    text: str, client: ClassifyClient, *, verbose: bool = True
) -> ClassifyResult:
    """Run the MCP tool-use classification sequence on *text*.

    When *verbose* is ``True`` each tool call and its result are printed to
    stdout, reproducing what an LLM agent would emit in a tool-use session.
    """

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log("\n[tool: audit_document_markings]")
    log(f"  input: {len(text)} characters")
    audit = client.audit(text)
    log(f"  overall: {audit.whole!r}  verdict: {audit.overall_verdict}")
    log(
        f"  found {len(audit.parts)} part marking(s): {[p.marking for p in audit.parts]}"
    )
    failed = [p.marking for p in invalid_parts(audit)]
    if failed:
        log(f"  failed validation: {failed}")

    # Aggregate takes each distinct settled marking once, in document order.
    inputs = list(
        dict.fromkeys(part.validation.rendered for part in valid_parts(audit))
    )

    log("\n[tool: aggregate_markings]")
    log(f"  inputs: {inputs}")

    aggregate: AggregateResult | None = None
    if not inputs:
        log("  result: (no valid part markings)")
    else:
        aggregate = client.aggregate(inputs)
        log(f"  overall: {aggregate.rendered!r}")

    return ClassifyResult(audit=audit, aggregate=aggregate)


def _reasons(errors: list[ValidationError]) -> list[str]:
    """Return the messages of the errors that make a marking not valid.

    Warnings are advisory and never set ``valid`` to false, so they are not
    reasons a marking failed.
    """
    return [e.message for e in errors if e.severity != "warning"]


def print_report(result: ClassifyResult) -> None:
    """Print a structured classification report to stdout."""
    audit = result.audit
    bar = "━" * 52
    print(f"\n{bar}")
    print(" CLASSIFICATION REPORT")
    print(bar)

    print(f"\n Markings Found ({len(audit.parts)})")
    if audit.parts:
        for part in audit.parts:
            print(f"   {part.marking}")
    else:
        print("   (none)")

    print("\n Validation Issues")
    failed = invalid_parts(audit)
    if failed:
        for part in failed:
            print(f"   {part.marking!r}: failed validation")
            for reason in _reasons(part.validation.errors):
                print(f"     {reason}")
    else:
        print("   None")

    _print_authored_overall(audit)

    print("\n Overall Marking Required by the Parts")
    aggregate = result.aggregate
    if aggregate is None:
        print("   (no valid part markings to combine)")
    else:
        print(f"   {aggregate.rendered}")
        if not aggregate.valid:
            for reason in _reasons(aggregate.errors):
                print(f"     {reason}")

    # The aggregate result already carries the notices its concepts attach, so
    # this section costs no extra call. The notices operation exists for
    # callers holding assertions that never went through validate, audit or
    # aggregate.
    print("\n Handling Notices")
    if aggregate is not None and aggregate.notices:
        for notice in aggregate.notices:
            required = " (acknowledgment required)" if notice.required else ""
            print(f"   {notice.concept_name}: {notice.text}{required}")
    else:
        print("   None")

    print(f"\n{bar}")


def _print_authored_overall(audit: DocumentAuditReport) -> None:
    """Print the overall marking the author wrote and whether it covers the parts."""
    print("\n Authored Overall Marking")
    if audit.whole is None:
        print("   (none found)")
    else:
        print(f"   {audit.whole}")
        whole = audit.whole_validation
        if whole is not None and not whole.valid:
            print("   Failed validation:")
            for reason in _reasons(whole.errors):
                print(f"     {reason}")

    coverage = audit.whole_covers_parts
    if coverage is None:
        print("   Covers the parts: not assessed")
    elif coverage.covered:
        print("   Covers the parts: yes")
    else:
        print("   Covers the parts: no")
        if coverage.missing_labels:
            print(f"     Missing: {', '.join(coverage.missing_labels)}")
        if coverage.excess_labels:
            print(
                f"     Not supported by the parts: {', '.join(coverage.excess_labels)}"
            )
        for reason in _reasons(coverage.refusals or []):
            print(f"     {reason}")

    for flag in audit.procedural_flags:
        print(f"   Procedural finding: {flag}")
    print(f"   Document verdict: {audit.overall_verdict}")
