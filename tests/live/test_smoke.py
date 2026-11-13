"""Live wire-contract smoke test against a real EzClassify REST runtime.

The replayer/conformance suites exercise the client against *recorded* fixtures.
That cannot catch a base-path or version mismatch: if the SDK and the live
server disagreed about the ``/v1`` prefix, the fixtures would still pass while
every real call 404s. This test closes that gap by running ``process()``,
``validate()`` and ``/v1/health`` (``client.ping()``) through the real
``ezclassify-rest-client`` against a live server.

Run with ``make smoke URL=<server-url>`` against a caller-provided licensed
and content-configured deployment. This lane is separate from standalone
recording replay and fails when its prerequisites are unavailable.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Iterator

import pytest
from ezclassify_rest_client import (
    EzClassifyClient,
    EzClassifyClientError,
    RestClientCredentials,
)

_SCHEME_ID = os.environ.get("EZC_SMOKE_CONTEXT_ID", "cedar-valley-protection")
_PROCESS_INPUT = os.environ.get("EZC_SMOKE_INPUT", "confidential")
_PROCESS_EXPECTED = os.environ.get("EZC_SMOKE_EXPECTED", "CONFIDENTIAL")
# Outputs process is asked to write into `renders`, which holds only the ones
# named. The defaults are formats of the default Context's scheme.
_PROCESS_OUTPUTS = os.environ.get("EZC_SMOKE_OUTPUTS", "default,short").split(",")


def _credentials() -> object:
    return RestClientCredentials(
        access_token=os.environ.get("EZC_SMOKE_ACCESS_TOKEN"),
        context_token=os.environ.get("EZC_SMOKE_CONTEXT_TOKEN"),
    )


@pytest.fixture(scope="module")
def live_server() -> Iterator[str]:
    """Require a caller-provided licensed REST deployment for the live lane."""
    base = os.environ.get("EZC_SMOKE_URL")
    if not base:
        pytest.fail("EZC_SMOKE_URL is required for make smoke URL=<server-url>")
    base = base.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/v1/health", timeout=10) as response:  # noqa: S310
            assert response.status == 200
    except (urllib.error.URLError, OSError) as error:
        pytest.fail(f"live REST deployment is unavailable: {error}")
    yield base


def test_live_ping_reports_v1_engine_version(live_server: str) -> None:
    """``client.ping()`` hits ``/v1/health`` and returns the live engine version.

    A wrong base path would 404 here and raise, not return 1.0.0.
    """
    with EzClassifyClient(live_server, credentials=_credentials()) as client:
        ping = client.ping()
    assert ping.engine_version, "live server returned an empty engineVersion"
    assert ping.engine_version.split(".")[0] == "1", (
        f"expected a 1.x engine version, got {ping.engine_version!r}"
    )


def test_live_process_round_trips_through_v1(live_server: str) -> None:
    """A real process call uses a published Context route and parses.

    A base-path mismatch here is exactly what the recorded fixtures cannot catch.
    """
    with EzClassifyClient(live_server, credentials=_credentials()) as deployment:
        with deployment.context(_SCHEME_ID, "latest") as context:
            result = context.scheme.process(
                _PROCESS_INPUT, outputs=_PROCESS_OUTPUTS
            ).result
            reading = context.scheme.validate(_PROCESS_INPUT).result
            with pytest.raises(EzClassifyClientError) as refusal:
                context.scheme.render(
                    result.assertions,
                    output_format="authority_block",
                    preservation="full",
                )
    assert result.valid is True
    assert result.rendered == _PROCESS_EXPECTED
    assert result.recognition is not None
    assert result.recognition["status"] == "complete"
    assert set(result.renders) == set(_PROCESS_OUTPUTS), (
        "live server did not write exactly the outputs named"
    )
    assert all("assessment" in rendered for rendered in result.renders.values())
    # The reader's call settles the same way and answers the same verdicts.
    assert reading.valid is result.valid
    assert reading.input_was_valid is result.input_was_valid
    assert reading.rendered == result.rendered
    assert refusal.value.status_code == 400
    assert refusal.value.code == "INVALID_INPUT"
