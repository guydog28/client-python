"""Tests for the MCPClient subprocess plumbing.

Each test spawns a tiny scripted executable standing in for the ezclassify-mcp
binary, so the pipe-handling behavior is exercised for real: stderr draining,
receive timeouts, request-id matching, argument and environment hand-off, and
error reporting.
"""

from __future__ import annotations

import subprocess
import sys
from time import monotonic
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_client
from audit_builders import aggregate, audit_report, part
from mcp_client import MCPClient

# Answers every request with an empty result, echoing the request id.
_ECHO_SERVER = """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {}}), flush=True)
"""


@pytest.fixture(autouse=True)
def spawned(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Record every server the client spawns and reap survivors at teardown.

    The assertions in each test are about the client's own cleanup; this
    finalizer is the backstop so a failing test can never leave a server
    process behind.
    """
    procs: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        proc: subprocess.Popen[bytes] = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        procs.append(proc)
        return proc

    monkeypatch.setattr(mcp_client.subprocess, "Popen", recording_popen)
    yield procs
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _server(tmp_path: Path, body: str) -> str:
    """Write *body* as an executable Python script and return its path.

    The client runs its server path directly, as it runs the real binary.
    """
    path = tmp_path / "fake-ezclassify-mcp"
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def test_chatty_stderr_does_not_deadlock(tmp_path: Path) -> None:
    # stderr must be drained, or a server logging more than the OS pipe buffer
    # (~64KB) blocks forever mid-handshake.
    chatty = _server(
        tmp_path,
        """
import sys

junk = "x" * 65536
for _ in range(20):
    sys.stderr.write(junk + "\\n")
sys.stderr.flush()
"""
        + _ECHO_SERVER,
    )
    with MCPClient(mcp_server_path=chatty, timeout=15) as client:
        assert client.list_tools() == []


def test_server_is_spawned_directly_with_the_stdio_flag_and_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The binary is the process: no interpreter is put in front of it, it is
    # asked for stdio, and it inherits the runtime settings the operator exported.
    monkeypatch.setenv("EZCLASSIFY_ARTIFACT_DIR", "/var/lib/ezclassify")
    reporting = _server(
        tmp_path,
        """
import json
import os
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        tool = {"name": " ".join(sys.argv[1:]) + "|" + os.environ["EZCLASSIFY_ARTIFACT_DIR"]}
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [tool]}}), flush=True)
""",
    )
    with MCPClient(mcp_server_path=reporting, timeout=15) as client:
        tools = client.list_tools()
    assert [t["name"] for t in tools] == ["--transport=stdio|/var/lib/ezclassify"]


def test_recv_times_out_when_server_never_answers(
    tmp_path: Path, spawned: list[subprocess.Popen[bytes]]
) -> None:
    # The timeout constructor parameter bounds every receive, so a stalled
    # server cannot hang the client.
    mute = _server(tmp_path, "import time\nwhile True:\n    time.sleep(1)\n")
    with pytest.raises(RuntimeError, match="did not respond within"):
        with MCPClient(mcp_server_path=mute, timeout=2):
            pass
    # __exit__ never runs when __enter__ raises, so the client has to stop the
    # server itself or the process outlives the caller.
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def test_handshake_failure_surfaces_stderr(tmp_path: Path) -> None:
    # When the server dies during initialize, its stderr reaches the caller
    # instead of a generic message.
    crash = _server(
        tmp_path,
        "import sys\nsys.stderr.write('boom: missing scheme dir\\n')\nsys.exit(1)\n",
    )
    with pytest.raises(RuntimeError, match="boom: missing scheme dir"):
        with MCPClient(mcp_server_path=crash, timeout=10):
            pass


@pytest.mark.parametrize(
    "noise",
    [
        'json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"})',
        'json.dumps({"jsonrpc": "2.0", "id": 999, "result": {}})',
        '"still starting"',
    ],
    ids=["notifications", "other-response-ids", "non-json-logs"],
)
def test_trickled_noise_does_not_restart_the_response_deadline(
    tmp_path: Path, noise: str, spawned: list[subprocess.Popen[bytes]]
) -> None:
    noisy = _server(
        tmp_path,
        """
import json
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        print(NOISE, flush=True)
        time.sleep(0.03)
    print(json.dumps({"id": request["id"], "result": {}}), flush=True)
""".replace("NOISE", noise),
    )
    started = monotonic()
    with pytest.raises(RuntimeError, match="did not respond within"):
        with MCPClient(mcp_server_path=noisy, timeout=0.3):
            pass
    assert monotonic() - started < 1.0
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def test_recv_skips_messages_for_other_ids(tmp_path: Path) -> None:
    # _recv matches the request id, so a server-initiated request is never
    # mistaken for our response.
    noisy = _server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        # A server-initiated request (own id) and a notification arrive
        # before the actual response.
        print(json.dumps({"jsonrpc": "2.0", "id": 999, "method": "roots/list"}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"tools": [{"name": "audit_document_markings"}]}}), flush=True)
""",
    )
    with MCPClient(mcp_server_path=noisy, timeout=15) as client:
        tools = client.list_tools()
    assert [t["name"] for t in tools] == ["audit_document_markings"]


def test_noise_on_stdout_does_not_abort_the_request(tmp_path: Path) -> None:
    # A startup banner or a stray log write on stdout is not a protocol
    # message, and must not raise a decode error out of the tool call.
    noisy = _server(
        tmp_path,
        """
import json
import sys

print("ezclassify-mcp starting up", flush=True)
for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        print("still warming up", flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"tools": [{"name": "audit_document_markings"}]}}), flush=True)
""",
    )
    with MCPClient(mcp_server_path=noisy, timeout=15) as client:
        tools = client.list_tools()
    assert [t["name"] for t in tools] == ["audit_document_markings"]


def test_tool_level_error_is_reported_with_the_tool_name(tmp_path: Path) -> None:
    # A tool can report failure inside a successful JSON-RPC response; the
    # text is then a message, not the JSON payload.
    failing = _server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    if message.get("method") == "tools/call":
        result = {"isError": True, "content": [{"type": "text", "text": "context not found"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
""",
    )
    with MCPClient(
        context_id="demo-ctx", mcp_server_path=failing, timeout=15
    ) as client:
        with pytest.raises(
            RuntimeError, match="audit_document_markings.*context not found"
        ):
            client.audit("some text")


def test_tool_methods_before_start_raise_a_clear_error() -> None:
    client = MCPClient(
        context_id="demo-ctx", mcp_server_path="/nonexistent/ezclassify-mcp"
    )
    with pytest.raises(RuntimeError, match="is not started"):
        client.audit("some text")


def test_server_lookup_consults_only_the_path_for_the_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PATH is the one place the lookup consults; everything else is
    # MCP_SERVER_PATH.
    asked: list[str] = []

    def record(name: str) -> None:
        asked.append(name)

    monkeypatch.setattr(mcp_client.shutil, "which", record)
    with pytest.raises(RuntimeError, match="MCP_SERVER_PATH"):
        mcp_client._find_mcp_server()

    assert asked == ["ezclassify-mcp"]


def test_server_lookup_returns_the_binary_found_on_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_client.shutil, "which", lambda name: f"/opt/ezclassify/bin/{name}"
    )
    assert mcp_client._find_mcp_server() == "/opt/ezclassify/bin/ezclassify-mcp"


def test_tool_call_forwards_operator_context_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stdio transport still requires the signed Context authorization carrier."""
    monkeypatch.setenv("EZCLASSIFY_CONTEXT_TOKEN", "operator-test-carrier")
    client = MCPClient(context_id="ref-ctx-1", mcp_server_path="unused")
    sent: list[dict] = []
    monkeypatch.setattr(client, "_send", sent.append)
    monkeypatch.setattr(client, "_recv", lambda _id: {"result": {"content": []}})
    client._call_tool("audit_document_markings", {"text": "HIGH"})
    assert sent[0]["params"]["_meta"] == {
        "ezclassifyContextToken": "operator-test-carrier"
    }
    assert sent[0]["params"]["arguments"] == {"text": "HIGH"}


def test_explicit_context_authorization_overrides_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EZCLASSIFY_CONTEXT_TOKEN", "ambient-test-carrier")
    carrier = "explicit-test-carrier"
    client = MCPClient(mcp_server_path="unused", context_token=carrier)
    sent: list[dict] = []
    monkeypatch.setattr(client, "_send", sent.append)
    monkeypatch.setattr(client, "_recv", lambda _id: {"result": {"content": []}})
    client._call_tool("audit_document_markings", {"text": "HIGH"})
    assert sent[0]["params"]["_meta"] == {"ezclassifyContextToken": carrier}


def test_tool_call_without_context_authorization_does_not_invent_a_carrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EZCLASSIFY_CONTEXT_TOKEN", raising=False)
    client = MCPClient(mcp_server_path="unused")
    sent: list[dict] = []
    monkeypatch.setattr(client, "_send", sent.append)
    monkeypatch.setattr(client, "_recv", lambda _id: {"result": {"content": []}})
    client._call_tool("audit_document_markings", {"text": "HIGH"})
    assert "_meta" not in sent[0]["params"]


def _stub_tool(
    client: MCPClient, monkeypatch: pytest.MonkeyPatch, payload: object
) -> list[tuple[str, dict]]:
    """Answer every tool call with *payload* and record what was sent."""
    calls: list[tuple[str, dict]] = []

    def answer(name: str, arguments: dict) -> object:
        calls.append((name, arguments))
        return payload

    monkeypatch.setattr(client, "_call_tool", answer)
    return calls


def test_audit_reads_the_typed_report_from_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MCPClient(context_id="ref-ctx-1", mcp_server_path="unused")
    wire = audit_report([part("HIGH"), part("BOGUS", 10, valid=False)], whole="HIGH")
    calls = _stub_tool(client, monkeypatch, {"result": wire.model_dump(by_alias=True)})

    report = client.audit("HIGH text")

    assert calls == [
        (
            "audit_document_markings",
            {"ctxId": "ref-ctx-1", "version": "latest", "text": "HIGH text"},
        )
    ]
    assert report == wire
    assert [p.validation.valid for p in report.parts] == [True, False]


def test_aggregate_reads_the_typed_result_from_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MCPClient(
        context_id="ref-ctx-1", context_version="2.0.0", mcp_server_path="unused"
    )
    wire = aggregate("HIGH")
    calls = _stub_tool(client, monkeypatch, {"result": wire.model_dump(by_alias=True)})

    result = client.aggregate(["HIGH", "LOW"])

    assert calls == [
        (
            "aggregate_markings",
            {"ctxId": "ref-ctx-1", "version": "2.0.0", "inputs": ["HIGH", "LOW"]},
        )
    ]
    assert result == wire


@pytest.mark.parametrize("payload", [None, [], {}, {"result": None}, {"result": []}])
def test_audit_refuses_a_payload_without_a_typed_result(
    payload: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MCPClient(context_id="ref-ctx-1", mcp_server_path="unused")
    _stub_tool(client, monkeypatch, payload)
    with pytest.raises(RuntimeError, match="audit_document_markings returned no typed"):
        client.audit("HIGH")


@pytest.mark.parametrize("payload", [None, {}, {"result": "HIGH"}])
def test_aggregate_refuses_a_payload_without_a_typed_result(
    payload: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MCPClient(context_id="ref-ctx-1", mcp_server_path="unused")
    _stub_tool(client, monkeypatch, payload)
    with pytest.raises(RuntimeError, match="aggregate_markings returned no typed"):
        client.aggregate(["HIGH"])


def test_a_tool_call_without_a_context_id_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EZCLASSIFY_CONTEXT_ID", raising=False)
    client = MCPClient(mcp_server_path="unused")
    with pytest.raises(RuntimeError, match="EZCLASSIFY_CONTEXT_ID"):
        client.audit("HIGH")
