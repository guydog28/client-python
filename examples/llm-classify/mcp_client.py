"""MCP JSON-RPC client that spawns @ezclassify/mcp as a stdio subprocess.

Speaks JSON-RPC over stdio with the stdlib alone; the wire types come from
ezclassify-contract. Provides the same audit / aggregate
interface as EzClassifyClient so it can be dropped in as a backend for the
classify() workflow.

Environment variables (the runtime's license and bundle settings are also required):
    EZCLASSIFY_CONTEXT_ID        : published Context id
    EZCLASSIFY_CONTEXT_VERSION   : Context version (default: latest)
    EZCLASSIFY_CONTEXT_TOKEN     : signed Context authorization carrier
    MCP_SERVER_PATH              : path to @ezclassify/mcp dist/index.js
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections import deque
from queue import Empty, Queue
from time import monotonic
from typing import Any

from ezclassify_contract import AggregateResult, DocumentAuditReport


_NOT_STARTED = (
    "MCP client is not started; use it as a context manager or call start() first"
)


class MCPClient:
    """Python MCP client that spawns @ezclassify/mcp as a subprocess.

    Communicates via JSON-RPC 2.0 over stdio. Provides the same audit /
    aggregate interface as EzClassifyClient, making it a drop-in backend
    for the classify() workflow.

    Use as a context manager to guarantee subprocess cleanup::

        with MCPClient() as client:
            report = client.audit("document text")
    """

    def __init__(
        self,
        context_id: str | None = None,
        context_version: str | None = None,
        mcp_server_path: str | None = None,
        timeout: int = 30,
        context_token: str | None = None,
    ) -> None:
        """Configure a subprocess connection without starting the runtime.

        Args:
            context_id: Published Context id, or EZCLASSIFY_CONTEXT_ID.
            context_version: Context version, or EZCLASSIFY_CONTEXT_VERSION.
            mcp_server_path: Configured runtime entrypoint, or MCP_SERVER_PATH.
            timeout: Maximum seconds to wait for each JSON-RPC response.
            context_token: Signed Context carrier, overriding EZCLASSIFY_CONTEXT_TOKEN.

        Raises:
            RuntimeError: If no runtime entrypoint can be located.
        """
        self._context_id = context_id or os.environ.get("EZCLASSIFY_CONTEXT_ID")
        self._context_version = context_version or os.environ.get(
            "EZCLASSIFY_CONTEXT_VERSION", "latest"
        )
        self._mcp_server_path = (
            mcp_server_path or os.environ.get("MCP_SERVER_PATH") or _find_mcp_server()
        )
        self._context_token = (
            context_token
            if context_token is not None
            else os.environ.get("EZCLASSIFY_CONTEXT_TOKEN")
        )
        self._timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._id_counter: int = 1
        self._stdout_lines: Queue[bytes | None] = Queue()
        self._stderr_tail: deque[str] = deque(maxlen=100)

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        """Spawn the MCP server subprocess and complete the JSON-RPC handshake."""
        env = dict(os.environ)
        # The runtime to spawn is chosen by the operator through
        # MCP_SERVER_PATH or a local install, and node is taken from PATH the
        # same way every other tool in the example is.
        self._proc = subprocess.Popen(  # noqa: S603
            ["node", self._mcp_server_path, "--transport=stdio"],  # noqa: S607
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._id_counter = 1
        self._stdout_lines = Queue()
        self._stderr_tail = deque(maxlen=100)
        # Both pipes are drained by daemon threads. stdout lines feed _recv
        # through a queue so it can time out; stderr is consumed continuously
        # (an undrained pipe fills up and deadlocks a chatty server) and its
        # tail is kept for error reporting.
        threading.Thread(
            target=_pump_stdout,
            args=(self._proc.stdout, self._stdout_lines),
            daemon=True,
        ).start()
        threading.Thread(
            target=_pump_stderr,
            args=(self._proc.stderr, self._stderr_tail),
            daemon=True,
        ).start()
        try:
            self._initialize()
        except BaseException:
            # ``with MCPClient()`` never calls __exit__ when __enter__ raises,
            # so a handshake that times out or fails would otherwise leave the
            # server running (orphaned once this process exits).
            self.stop()
            raise

    def stop(self) -> None:
        """Terminate the MCP server subprocess."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
                self._proc.wait()
            finally:
                self._proc = None

    def _context_args(self) -> dict[str, str]:
        """Return the Context selectors required by every demo tool call."""
        if not self._context_id:
            raise RuntimeError("set EZCLASSIFY_CONTEXT_ID or pass context_id")
        return {"ctxId": self._context_id, "version": self._context_version}

    def audit(self, text: str) -> DocumentAuditReport:
        """Audit a document through the Context-scoped MCP audit tool."""
        return DocumentAuditReport.from_dict(
            self._call_for_result("audit_document_markings", {"text": text})
        )

    def aggregate(self, markings: list[str]) -> AggregateResult:
        """Aggregate markings through the Context-scoped MCP aggregate tool."""
        return AggregateResult.from_dict(
            self._call_for_result("aggregate_markings", {"inputs": markings})
        )

    def _call_for_result(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a Context tool and return the typed ``result`` of its envelope."""
        payload = self._call_tool(name, {**self._context_args(), **arguments})
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError(f"{name} returned no typed result")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        """List the tools the MCP server exposes via the ``tools/list`` JSON-RPC call.

        Returns the raw tool descriptors (``name``, ``description``,
        ``inputSchema``) so callers can hand them to an LLM that drives
        the server through tool calls.
        """
        req_id = self._id_counter
        self._id_counter += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/list",
                "params": {},
            }
        )
        resp = self._recv(req_id)
        if "error" in resp:
            raise RuntimeError(f"MCP tools/list error: {resp['error']}")
        tools = resp.get("result", {}).get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an arbitrary MCP tool and return the parsed JSON payload.

        Unlike :meth:`audit` / :meth:`aggregate`, this
        method makes no assumptions about *name*, useful when an LLM
        agent decides which tool to invoke and the orchestrator must
        forward that decision to the server unchanged.
        """
        return self._call_tool(name, arguments)

    def _send(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError(_NOT_STARTED)
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        self._proc.stdin.flush()

    def _recv(self, req_id: int) -> dict[str, Any]:
        """Wait for the response to *req_id*, bounded by the client timeout.

        Notifications (no ``id``) and messages for other ids are skipped so a
        server-initiated request is never mis-consumed as our response.
        """
        if self._proc is None:
            raise RuntimeError(_NOT_STARTED)
        deadline = monotonic() + self._timeout
        while True:
            try:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise Empty
                line = self._stdout_lines.get(timeout=remaining)
            except Empty:
                raise RuntimeError(
                    f"MCP server did not respond within {self._timeout}s"
                    f"{self._stderr_excerpt()}"
                ) from None
            if line is None:
                raise RuntimeError(
                    f"MCP server closed stdout unexpectedly{self._stderr_excerpt()}"
                )
            try:
                msg: dict[str, Any] = json.loads(line.decode())
            except ValueError:
                # A startup banner or a stray log write on stdout is not a
                # protocol message. Keep it in the stderr tail for diagnostics
                # and keep waiting for the response.
                self._stderr_tail.append(
                    f"[non-JSON stdout line] {line.decode(errors='replace')}"
                )
                continue
            if msg.get("id") == req_id:
                return msg

    def _stderr_excerpt(self) -> str:
        """Return the captured stderr tail as a message suffix, if any."""
        tail = "".join(self._stderr_tail).strip()
        return f"\nMCP server stderr:\n{tail}" if tail else ""

    def _initialize(self) -> None:
        """Perform the MCP initialize / notifications/initialized handshake."""
        req_id = self._id_counter
        self._id_counter += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llm-classify", "version": "1.0.0"},
                },
            }
        )
        resp = self._recv(req_id)
        if "error" in resp:
            raise RuntimeError(
                f"MCP initialize failed: {resp['error']}{self._stderr_excerpt()}"
            )
        self._send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool and return the deserialized result payload."""
        req_id = self._id_counter
        self._id_counter += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                    **(
                        {"_meta": {"ezclassifyContextToken": self._context_token}}
                        if self._context_token
                        else {}
                    ),
                },
            }
        )
        resp = self._recv(req_id)
        if "error" in resp:
            raise RuntimeError(f"MCP tool error ({name}): {resp['error']}")
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = ""
        if content and isinstance(content[0], dict):
            text = content[0].get("text") or ""
        # A tool can report its own failure inside a successful JSON-RPC
        # response, and the text is then a human-readable message rather than
        # the JSON payload.
        if result.get("isError"):
            raise RuntimeError(f"MCP tool error ({name}): {text or 'no detail'}")
        if not content:
            return None
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError as exc:
            raise RuntimeError(
                f"MCP tool ({name}) returned a non-JSON result payload"
            ) from exc


def _pump_stdout(stream: Any, lines: "Queue[bytes | None]") -> None:
    """Feed stdout lines into the queue; ``None`` marks end of stream."""
    for line in iter(stream.readline, b""):
        lines.put(line)
    lines.put(None)


def _pump_stderr(stream: Any, tail: "deque[str]") -> None:
    """Consume stderr continuously, keeping only the most recent lines."""
    for line in iter(stream.readline, b""):
        tail.append(line.decode(errors="replace"))


def _find_mcp_server() -> str:
    """Locate the @ezclassify/mcp dist/index.js file.

    Looks in this directory's ``node_modules``. Any other location, a build
    sitting in another checkout included, is named through MCP_SERVER_PATH.
    """
    here = os.path.dirname(os.path.abspath(__file__))

    local = os.path.join(here, "node_modules", "@ezclassify", "mcp", "dist", "index.js")
    if os.path.isfile(local):
        return local

    raise RuntimeError(
        "Cannot locate @ezclassify/mcp server. Set MCP_SERVER_PATH or install:\n"
        "  npm install @ezclassify/mcp\n"
        "Configure the runtime license and signed content bundle before starting it."
    )
