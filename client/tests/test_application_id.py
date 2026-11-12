"""The application id is sent on Context requests only and is never a credential."""

from typing import Any

import httpx
import pytest
import respx

from ezclassify_rest_client import (
    EzClassifyClient,
    EzClassifyClientError,
    EzClassifyContext,
    RestClientCredentials,
    connect_context,
)

_BASE = "https://runtime.example.test"
_HEADER = "x-ezclassify-application-id"
_APP = "case-intake-portal"


def _description(context_id: str = "default") -> dict[str, Any]:
    return {
        "id": context_id,
        "version": "1.0.0",
        "scheme": {"id": "levels", "version": "1.0.0", "resolvedVersion": "1.0.0"},
        "schemes": [
            {"selector": "levels", "id": "levels", "version": "1.0.0", "roles": []}
        ],
    }


@respx.mock
def test_deployment_client_sends_the_id_on_context_routes_not_health() -> None:
    contexts = respx.get(f"{_BASE}/v1/ctx").respond(200, json={"contexts": ["default"]})
    versions = respx.get(f"{_BASE}/v1/ctx/default").respond(
        200, json={"id": "default", "versions": ["1.0.0"]}
    )
    describe = respx.get(f"{_BASE}/v1/ctx/default/1.0.0").respond(
        200,
        json=_description(),
        headers={"X-EzClassify-Resolved-Version": "1.0.0"},
    )
    health = respx.get(f"{_BASE}/v1/health").respond(
        200,
        json={
            "status": "ok",
            "engineVersion": "1.0.0",
            "engineSha": "",
            "gitTag": "",
            "openapiVersion": "1.0.0",
            "abiVersion": "v1",
        },
    )
    with EzClassifyClient(
        _BASE, headers={"X-Customer": "preserved"}, application_id=_APP
    ) as client:
        assert client.list_contexts() == ["default"]
        assert client.list_context_versions("default") == ["1.0.0"]
        client.ping()
        with client.context("default", "1.0.0"):
            pass
    for route in (contexts, versions, describe):
        sent = route.calls.last.request.headers
        assert sent[_HEADER] == _APP
        assert sent["X-Customer"] == "preserved"
        assert "authorization" not in sent
    assert _HEADER not in health.calls.last.request.headers


@pytest.mark.parametrize("factory", [EzClassifyContext, connect_context])
@respx.mock
def test_context_handle_sends_the_id_with_a_user_bearer_on_every_request(
    factory: Any,
) -> None:
    describe = respx.get(f"{_BASE}/v1/ctx/default/1.0.0").respond(
        200,
        json=_description(),
        headers={"X-EzClassify-Resolved-Version": "1.0.0"},
    )
    refusal = respx.post(f"{_BASE}/v1/ctx/default/1.0.0/scheme/validate").respond(
        403,
        json={"error": "Refused"},
        headers={"X-EzClassify-Resolved-Version": "1.0.0"},
    )
    with factory(
        _BASE,
        context_id="default",
        context_version="1.0.0",
        credentials=RestClientCredentials(access_token="caller"),
        application_id=_APP,
    ) as context:
        with pytest.raises(EzClassifyClientError) as caught:
            context.scheme.validate("ALPHA")
    assert caught.value.status_code == 403
    assert refusal.call_count == 1
    assert describe.call_count == (1 if factory is connect_context else 0)
    for call in respx.calls:
        assert call.request.headers[_HEADER] == _APP
        assert call.request.headers["authorization"] == "Bearer caller"


@pytest.mark.parametrize("factory", [EzClassifyClient, EzClassifyContext])
@respx.mock
def test_no_id_means_no_header(factory: Any) -> None:
    route = respx.get(f"{_BASE}/v1/ctx").respond(200, json={"contexts": []})
    respx.get(f"{_BASE}/v1/ctx/default/1.0.0").respond(
        200,
        json=_description(),
        headers={"X-EzClassify-Resolved-Version": "1.0.0"},
    )
    if factory is EzClassifyClient:
        with factory(_BASE) as client:
            client.list_contexts()
        assert _HEADER not in route.calls.last.request.headers
    else:
        with factory(_BASE, context_id="default", context_version="1.0.0") as ctx:
            ctx.resolve()
        assert _HEADER not in respx.calls.last.request.headers


@pytest.mark.parametrize("application_id", ["!", "a" * 128, "~case.intake_portal-1"])
def test_application_id_inside_the_grammar_is_accepted(application_id: str) -> None:
    with EzClassifyClient(_BASE, application_id=application_id):
        pass


@pytest.mark.parametrize(
    "factory", [EzClassifyClient, EzClassifyContext, connect_context]
)
@pytest.mark.parametrize(
    "application_id",
    [
        "",
        "   ",
        " leading",
        "trailing ",
        "line\r\nbreak",
        "tab\tvalue",
        "null\x00",
        "del\x7f",
        "café",
        "inner space",
        "a" * 129,
    ],
)
def test_malformed_application_id_refuses_before_client_creation(
    factory: Any, application_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_transport(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("invalid application id reached HTTP transport")

    monkeypatch.setattr(httpx, "Client", refuse_transport)
    arguments: dict[str, Any] = {"application_id": application_id}
    if factory is not EzClassifyClient:
        arguments["context_id"] = "default"
    with pytest.raises(ValueError, match="application_id"):
        factory(_BASE, **arguments)


@pytest.mark.parametrize("context_id", [".", ".."])
@pytest.mark.parametrize("factory", [EzClassifyContext, connect_context])
def test_context_dot_segments_refuse_before_transport(
    factory: Any, context_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_transport(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dot segment reached transport")

    monkeypatch.setattr(httpx, "Client", refuse_transport)
    with pytest.raises(ValueError, match="context_id"):
        factory(_BASE, context_id=context_id, application_id=_APP)


@pytest.mark.parametrize("context_id", [".", ".."])
@respx.mock
def test_discovery_dot_segments_do_not_make_requests(context_id: str) -> None:
    with EzClassifyClient(_BASE, application_id=_APP) as client:
        with pytest.raises(ValueError, match="context_id"):
            client.list_context_versions(context_id)
    assert len(respx.calls) == 0


@pytest.mark.parametrize("context_version", [".", ".."])
@pytest.mark.parametrize("factory", [EzClassifyContext, connect_context])
def test_version_dot_segments_refuse_before_transport(
    factory: Any, context_version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_transport(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("version dot segment reached transport")

    monkeypatch.setattr(httpx, "Client", refuse_transport)
    with pytest.raises(ValueError, match="context_version"):
        factory(
            _BASE,
            context_id="default",
            context_version=context_version,
            application_id=_APP,
        )
