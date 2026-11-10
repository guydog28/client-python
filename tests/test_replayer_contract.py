"""Replayer-contract corpus test for the Python HTTP stub server.

Runs every case in the vendored vendor/spec/replayer-contract/v1/corpus.json
against a fresh Replayer instance. All cases must pass before the replayer is permitted
to run engine-slice conformance. Also pins the replayer's malformed-JSON response.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

import pytest

from ezclassify._replayer import Replayer

_CORPUS_PATH = (
    Path(__file__).parent.parent
    / "vendor"
    / "spec"
    / "replayer-contract"
    / "v1"
    / "corpus.json"
)


def _subset_match(actual: Any, expected: Any) -> bool:
    """Recursively verify every key in expected is present and equal in actual."""
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, (int, float)):
        # bool is an int subclass; True must not satisfy an expected 1.
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and float(actual) == float(expected)
        )
    if isinstance(expected, str):
        return actual == expected
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) < len(expected):
            return False
        return all(_subset_match(actual[i], expected[i]) for i in range(len(expected)))
    if isinstance(expected, dict):
        if isinstance(actual, list):
            # An object read against an array addresses it as a JavaScript
            # lookup does, the way the Node reference matcher reads it: decimal
            # keys name elements and "length" pins the exact count.
            return all(
                _subset_match(_array_member(actual, k), v) for k, v in expected.items()
            )
        if not isinstance(actual, dict):
            return False
        return all(_subset_match(actual.get(k), v) for k, v in expected.items())
    return expected == actual


def _array_member(actual: list, key: str) -> Any:
    """Read ``key`` from ``actual`` as a JavaScript property lookup would."""
    if key == "length":
        return len(actual)
    if key.isdecimal() and str(int(key)) == key and int(key) < len(actual):
        return actual[int(key)]
    return None


def _load_corpus() -> dict:
    """Load the replayer-contract corpus from vendor/."""
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _send_request(
    replayer_url: str,
    method: str,
    path: str,
    headers: dict,
    body: Any,
    raw_body: Optional[str] = None,
) -> tuple[int, Any]:
    """Send optional verbatim UTF-8 wire bytes and return status and parsed body."""
    url = replayer_url + path
    body_bytes = (
        raw_body.encode("utf-8")
        if raw_body is not None
        else json.dumps(body).encode("utf-8")
    )
    req = urllib.request.Request(url, data=body_bytes, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    if not req.get_header("Content-type"):
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _collect_cases() -> list[dict]:
    """Return all corpus cases as a flat list."""
    corpus = _load_corpus()
    return corpus["cases"]


def test_arg_order_uses_raw_wire_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """The corpus's reversed wire keys must reach the replayer unchanged."""
    request = next(c["request"] for c in _collect_cases() if c["id"] == "arg-order")
    raw_body = request["rawBody"].encode("utf-8")
    assert json.loads(raw_body) == request["body"]
    assert raw_body != json.dumps(request["body"]).encode("utf-8")
    sent: list[bytes] = []

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def capture(req: urllib.request.Request) -> Response:
        sent.append(req.data)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    _send_request(
        "http://example.invalid",
        request["method"],
        request["path"],
        request["headers"],
        request["body"],
        request["rawBody"],
    )
    assert sent == [raw_body]


@pytest.mark.parametrize(
    "case", _collect_cases(), ids=[c["id"] for c in _collect_cases()]
)
def test_replayer_contract_case(case: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run one corpus case against a fresh Replayer and assert status and body."""
    recordings: dict[str, dict] = {
        hash_key: {"statusCode": rec["statusCode"], "body": rec["body"]}
        for hash_key, rec in case["replayerRecordings"].items()
    }

    replayer = Replayer(recordings)
    try:
        request = case["request"]
        if "rawBody" in request:
            expected_wire = request["rawBody"].encode("utf-8")
            assert json.loads(expected_wire) == request["body"]
            original_urlopen = urllib.request.urlopen

            def observe_wire(req: urllib.request.Request) -> Any:
                assert req.data == expected_wire
                return original_urlopen(req)

            monkeypatch.setattr(urllib.request, "urlopen", observe_wire)
        status, actual = _send_request(
            replayer.url,
            request["method"],
            request["path"],
            request.get("headers", {}),
            request["body"],
            request.get("rawBody"),
        )
    finally:
        replayer.close()

    assert status == case["expectedStatus"], (
        f"status mismatch: got {status}, want {case['expectedStatus']}\nbody: {actual}"
    )

    if case["expectedStatus"] == 200 and "expectedBody" in case:
        assert _subset_match(actual, case["expectedBody"]), (
            f"body subset mismatch\n  want: {json.dumps(case['expectedBody'], indent=2)}\n  got:  {json.dumps(actual, indent=2)}"
        )

    if case["expectedStatus"] == 404 and "expectedMissEnvelope" in case:
        assert _subset_match(actual, case["expectedMissEnvelope"]), (
            f"miss envelope mismatch\n  want: {json.dumps(case['expectedMissEnvelope'], indent=2)}\n  got:  {json.dumps(actual, indent=2)}"
        )


class TestReplayerInvalidJson:
    """The replayer answers a malformed request body with a 400 invalid_json error."""

    def test_post_malformed_json_returns_400(self):
        replayer = Replayer({})
        try:
            req = urllib.request.Request(
                replayer.url + "/api/scheme/test/process",
                data=b"{ not : valid : json }",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    status = resp.status
                    body = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                status = exc.code
                body = json.loads(exc.read())
        finally:
            replayer.close()

        assert status == 400
        assert body.get("error") == "invalid_json"
        assert "message" in body
