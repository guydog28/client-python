"""Opt-in end-to-end tests for the llm-classify CLI in licensed MCP mode.

These tests spawn the real ezclassify-mcp binary as a subprocess and run the
CLI against it, no mocked HTTP calls, no fake JSON-RPC responses. The caller
supplies an already licensed MCP runtime configured with the signed content
for the ``cedar-valley`` Context, the demo's default (override it with
EZCLASSIFY_CONTEXT_ID). The audit needs a scheme with a whole form and a part
form, which Cedar Valley has.

Requires: Python 3.11+ and the ezclassify-mcp binary from a runtime release archive.
MCP_SERVER_PATH must explicitly select that binary.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

APP_DIR = Path(__file__).resolve().parents[2]
_env_mcp = os.environ.get("MCP_SERVER_PATH")
MCP_SERVER = Path(_env_mcp) if _env_mcp else None

SAMPLE_FILE = APP_DIR / "sample.txt"


@pytest.fixture(scope="module", autouse=True)
def configured_mcp() -> None:
    """Fail the explicit MCP lane if its licensed runtime is unavailable."""
    if MCP_SERVER is None or not MCP_SERVER.is_file():
        pytest.fail(
            "MCP_SERVER_PATH must name a licensed, content-configured MCP runtime"
        )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI in MCP mode and require it to exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "main", *args, "--mcp"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    return result


def _sample_report() -> str:
    return _run_cli("--file", str(SAMPLE_FILE), "--quiet").stdout


def test_mcp_mode_prints_each_tool_call() -> None:
    """The verbose run shows the audit call and the aggregate call it feeds."""
    out = _run_cli("--file", str(SAMPLE_FILE)).stdout
    assert "[tool: audit_document_markings]" in out
    assert "found 4 part marking(s): ['(P)', '(P)', '(C)', '(I)']" in out
    assert "[tool: aggregate_markings]" in out
    assert "inputs: ['PUBLIC', 'CONFIDENTIAL', 'INTERNAL']" in out


def test_mcp_mode_structured_report() -> None:
    """MCP-mode output contains the required structured-report sections."""
    out = _sample_report()
    assert "CLASSIFICATION REPORT" in out
    assert "Markings Found" in out
    assert "Validation Issues" in out
    assert "Authored Overall Marking" in out
    assert "Overall Marking Required by the Parts" in out
    assert "Handling Notices" in out


def test_mcp_mode_finds_every_part_marking() -> None:
    """The audit finds the four part markings in the memo, in document order."""
    out = _sample_report()
    assert "Markings Found (4)\n   (P)\n   (P)\n   (C)\n   (I)\n" in out


def test_mcp_mode_no_validation_issues() -> None:
    """Every part marking in the memo is valid."""
    assert "Validation Issues\n   None" in _sample_report()


def test_mcp_mode_authored_overall_covers_the_parts() -> None:
    """The memo's CONFIDENTIAL banner covers its parts."""
    out = _sample_report()
    assert "Authored Overall Marking\n   CONFIDENTIAL\n   Covers the parts: yes" in out


def test_mcp_mode_reports_the_procedural_finding_as_the_engine_gives_it() -> None:
    """The scheme infers a restriction the memo does not state, so the audit says so."""
    out = _sample_report()
    assert "Procedural finding: marking-needs-completion" in out
    assert "Document verdict: procedural-gap" in out


def test_mcp_mode_overall_marking_the_parts_require() -> None:
    """Aggregating the parts yields CONFIDENTIAL, the most restrictive of them."""
    out = _sample_report()
    assert "Overall Marking Required by the Parts\n   CONFIDENTIAL\n" in out


def test_mcp_mode_inline_text() -> None:
    """MCP mode also works with --text, and an all-public part needs only PUBLIC."""
    out = _run_cli(
        "--text",
        "CONFIDENTIAL\n\n(P) The route map is public.\n\nCONFIDENTIAL",
        "--quiet",
    ).stdout
    assert "Markings Found (1)\n   (P)\n" in out
    assert "Covers the parts: yes" in out
    assert "Overall Marking Required by the Parts\n   PUBLIC\n" in out


def test_mcp_mode_document_without_an_overall_marking() -> None:
    """A document with parts but no authored overall marking has none to cover them."""
    out = _run_cli("--text", "(P) No overall marking here.", "--quiet").stdout
    assert "Authored Overall Marking\n   (none found)" in out
    assert "Covers the parts: not assessed" in out
    assert "Overall Marking Required by the Parts\n   PUBLIC\n" in out


def test_mcp_client_context_manager_cleans_up() -> None:
    """MCPClient stops the subprocess when the context manager exits."""
    from mcp_client import MCPClient

    with MCPClient() as client:
        pid = client._proc.pid  # type: ignore[union-attr]
        report = client.audit(SAMPLE_FILE.read_text(encoding="utf-8"))

    assert len(report.parts) == 4

    try:
        os.kill(pid, 0)
        alive = True
    except (ProcessLookupError, PermissionError):
        alive = False
    assert not alive, f"MCP subprocess {pid} still running after context exit"


def test_mcp_client_audit_then_aggregate() -> None:
    """MCPClient drives the audit → aggregate sequence over the memo."""
    from classifier import classify, invalid_parts
    from mcp_client import MCPClient

    text = SAMPLE_FILE.read_text(encoding="utf-8")
    with MCPClient() as client:
        result = classify(text, client, verbose=False)

    assert [p.marking for p in result.audit.parts] == ["(P)", "(P)", "(C)", "(I)"]
    assert result.audit.whole == "CONFIDENTIAL"
    assert invalid_parts(result.audit) == []
    assert result.aggregate is not None
    assert result.aggregate.valid
    assert result.aggregate.rendered == "CONFIDENTIAL"
