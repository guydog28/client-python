"""Unit tests for the main CLI entry point."""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from audit_builders import aggregate, audit_report, part
from classifier import ClassifyResult
from main import main


@pytest.fixture(autouse=True)
def _no_live_context_client():
    """CLI unit tests exercise orchestration, never a real network connection."""
    with patch("main.EzClassifyClient") as client:
        client.return_value.__enter__.return_value = MagicMock()
        yield client


def _mock_classify(markings: list[str], overall: str) -> MagicMock:
    """Return a mock classify() that returns a stub ClassifyResult."""
    result = ClassifyResult(
        audit=audit_report([part(m) for m in markings], whole=overall),
        aggregate=aggregate(overall),
    )
    return MagicMock(return_value=result)


def test_exits_2_without_file_or_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--server", "http://localhost:3000", "--context", "cedar-valley"])
    assert rc == 2


def test_exits_2_with_both_file_and_text(tmp_path: "os.PathLike[str]") -> None:
    f = tmp_path / "doc.txt"
    f.write_text("HIGH text", encoding="utf-8")
    rc = main(["--file", str(f), "--text", "HIGH text"])
    assert rc == 2


def test_exits_2_for_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--file", "/does/not/exist.txt"])
    assert rc == 2


def test_exits_0_with_text_arg(capsys: pytest.CaptureFixture[str]) -> None:
    mock_fn = _mock_classify(["HIGH"], "HIGH")
    with patch("main.classify", mock_fn):
        rc = main(["--text", "HIGH text", "--quiet"])
    assert rc == 0


def test_exits_0_with_file_arg(
    tmp_path: "os.PathLike[str]",
    capsys: pytest.CaptureFixture[str],
) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("HIGH text", encoding="utf-8")
    mock_fn = _mock_classify(["HIGH"], "HIGH")
    with patch("main.classify", mock_fn):
        rc = main(["--file", str(f), "--quiet"])
    assert rc == 0


def test_prints_overall_marking(capsys: pytest.CaptureFixture[str]) -> None:
    mock_fn = _mock_classify(["HIGH"], "HIGH")
    with patch("main.classify", mock_fn):
        main(["--text", "HIGH text", "--quiet"])
    out = capsys.readouterr().out
    assert "Overall Marking Required by the Parts\n   HIGH\n" in out


def test_no_markings_prints_none_message(capsys: pytest.CaptureFixture[str]) -> None:
    result = ClassifyResult(audit=audit_report([]), aggregate=None)
    with patch("main.classify", return_value=result):
        main(["--text", "no markings here", "--quiet"])
    out = capsys.readouterr().out
    assert "Markings Found (0)" in out
    assert "(no valid part markings to combine)" in out


def test_api_error_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("main.classify", side_effect=RuntimeError("API error 500: oops")):
        rc = main(["--text", "HIGH text", "--quiet"])
    assert rc == 1


def test_quiet_flag_suppresses_tool_output(capsys: pytest.CaptureFixture[str]) -> None:
    mock_fn = _mock_classify(["HIGH"], "HIGH")
    with patch("main.classify", mock_fn) as mock:
        main(["--text", "HIGH text", "--quiet"])
    _, kwargs = mock.call_args
    assert kwargs.get("verbose") is False


def test_verbose_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    mock_fn = _mock_classify(["HIGH"], "HIGH")
    with patch("main.classify", mock_fn) as mock:
        main(["--text", "HIGH text"])
    _, kwargs = mock.call_args
    assert kwargs.get("verbose") is True


def test_rest_mode_sdk_error_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    # The SDK raises EzClassifyClientError, which is not a RuntimeError. A
    # refused connection is the most common failure here and it has to print
    # the error line, not a traceback.
    from ezclassify_rest_client import EzClassifyClientError

    with patch(
        "main.classify",
        side_effect=EzClassifyClientError("Connection error: refused"),
    ):
        rc = main(["--text", "HIGH text", "--quiet"])
    assert rc == 1
    assert "error: Connection error: refused" in capsys.readouterr().err


def test_mcp_mode_missing_binary_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    # Spawning the runtime raises FileNotFoundError when the binary is absent.
    import mcp_client

    with patch.object(
        mcp_client,
        "MCPClient",
        side_effect=FileNotFoundError("ezclassify-mcp not found"),
    ):
        rc = main(["--text", "HIGH text", "--mcp", "--quiet"])
    assert rc == 1
    assert "error: ezclassify-mcp not found" in capsys.readouterr().err
