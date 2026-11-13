"""CLI entry point for the llm-classify example app.

Two operating modes are supported, selected by the ``--mcp`` flag or the
``EZCLASSIFY_TRANSPORT`` environment variable:

**MCP mode** (``--mcp`` / ``EZCLASSIFY_TRANSPORT=mcp``)::

    python3 -m main --file sample.txt --mcp

Spawns the ``ezclassify-mcp`` runtime binary as a subprocess and drives the MCP
tool-use sequence directly (audit_document_markings → aggregate_markings).
The MCP runtime must be licensed and configured with its signed content bundle.
No LLM API key is required; the orchestration is deterministic.

**REST API mode** (default, no ``--mcp``)::

    python3 -m main --server https://runtime.example.com --context cedar-valley --file sample.txt

Connects to a running EzClassify runtime that serves the Context. The free
developer runtime serves ``cedar-valley`` with no credentials::

    docker run --rm -p 3000:8080 ghcr.io/ezclassify/developer-runtime

``--server`` defaults to ``http://localhost:3000``, where that container listens.

Environment variables
---------------------
EZCLASSIFY_TRANSPORT  mcp (default: use REST API)
EZCLASSIFY_ACCESS_TOKEN   caller identity token, if the runtime requires one
EZCLASSIFY_CONTEXT_TOKEN  signed Context token, if the runtime requires one
EZCLASSIFY_CONTEXT_ID  published Context ID (default: cedar-valley)
EZCLASSIFY_CONTEXT_VERSION  published Context version (default: the server's choice)
MCP_SERVER_PATH       path to the ezclassify-mcp binary (default: the one on PATH)
"""

from __future__ import annotations

import argparse
import os
import sys

from classifier import ClassifyResult, classify, print_report
from client import EzClassifyClient, credentials_from_env
from ezclassify_rest_client import EzClassifyClientError


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Classify a document using EzClassify via the MCP tool-use sequence.",
    )
    p.add_argument(
        "--mcp",
        action="store_true",
        default=os.environ.get("EZCLASSIFY_TRANSPORT", "").lower() == "mcp",
        help="Spawn a licensed, configured MCP runtime locally",
    )
    p.add_argument("--server", default="http://localhost:3000", help="Runtime base URL")
    p.add_argument(
        "--context",
        default=os.environ.get("EZCLASSIFY_CONTEXT_ID", "cedar-valley"),
        help="Published Context ID",
    )
    p.add_argument(
        "--context-version",
        default=os.environ.get("EZCLASSIFY_CONTEXT_VERSION"),
        help="Published Context version; omit it to let the server choose",
    )
    p.add_argument("--file", help="Path to a text file to classify")
    p.add_argument("--text", help="Inline text to classify")
    p.add_argument("--quiet", action="store_true", help="Suppress per-step tool output")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the LLM classify CLI."""
    args = _build_parser().parse_args(argv)

    if args.file and args.text:
        print("error: supply --file or --text, not both", file=sys.stderr)
        return 2
    if not args.file and not args.text:
        print("error: supply --file or --text", file=sys.stderr)
        return 2

    if args.file:
        try:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
            return 2
    else:
        text = args.text  # type: ignore[assignment]

    if args.mcp:
        return _run_mcp(text, args)
    return _run_rest(text, args)


def _run_mcp(text: str, args: argparse.Namespace) -> int:
    """Spawn the configured MCP runtime and drive its tool-use sequence."""
    from mcp_client import MCPClient

    try:
        with MCPClient(args.context, args.context_version) as client:
            result = classify(text, client, verbose=not args.quiet)
    except (RuntimeError, OSError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    print_report(result)
    return 0


def _run_rest(text: str, args: argparse.Namespace) -> int:
    """Run in REST API mode: connect to a running EzClassify REST API."""
    try:
        with EzClassifyClient(
            args.server,
            args.context,
            args.context_version,
            credentials=credentials_from_env(),
        ) as client:
            result: ClassifyResult = classify(text, client, verbose=not args.quiet)
    except (RuntimeError, EzClassifyClientError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
