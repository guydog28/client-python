"""Deployment-level HTTP client for EzClassify Context discovery and health.

Classification operations intentionally do not live here. Bind a published
Context with :meth:`EzClassifyClient.context` and use its scheme, guide, access,
document, and crosswalk groups.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Protocol,
    Tuple,
    TypeVar,
    Union,
)
from urllib.parse import quote

import httpx
from pydantic import ValidationError as PydanticValidationError

from ezclassify_contract.models import (
    _CtxListResponseBody,
    _CtxVersionsResponseBody,
    _HealthResponse,
)

from ._deadline import deadline_transport, request_deadline, require_timeout
from ._spec_version import CLIENT_SPEC_VERSION

logger = logging.getLogger(__name__)


class EzClassifyClientError(Exception):
    """Raised when the EzClassify REST API cannot satisfy a request.

    Every operation can answer 400 or 429, so both reach callers through this
    one type.

    Attributes:
        status_code: The HTTP status, or ``0`` when no response arrived.
        code: The stable machine-readable failure class, such as
            ``INVALID_INPUT``, when the server names one. A 400 carries
            ``INVALID_INPUT`` for a request the operation does not accept,
            including a query parameter or body field it does not declare.
        detail: What the failure is about, beside ``code``. For an undeclared
            query parameter it is ``query: <name>``.
        payload: The parsed JSON error object, or ``None`` when the body was
            not one.
        retry_after: Seconds to wait before sending the request again, set on
            a 429 from the ``Retry-After`` header and, when the header is
            absent or unusable, from the body's ``retryAfter``. ``None`` on
            every other error. The client never sleeps or retries on its own;
            waiting is the caller's decision, bounded however it chooses.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        *,
        code: str | None = None,
        detail: str | None = None,
        payload: Dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.payload = payload
        self.retry_after = retry_after


class MalformedResponseError(EzClassifyClientError):
    """Raised for a success response the wire contract does not allow.

    A 2xx whose body is not JSON, is not the shape the operation answers with,
    or has a member the contract requires missing at any depth, or null where
    the contract does not allow null. The answer is never cached and never
    handed back in part. This is a fault on the server's side of the wire or
    in something between, such as a proxy; the client raises ``ValueError``
    only for its own caller's input.

    Attributes:
        path: Where in the body the contract was broken, as a JSONPath from
            its root: ``$`` for the body itself, or a member such as
            ``$.result.errors[0].code``.
    """

    def __init__(self, message: str, status_code: int, *, path: str) -> None:
        super().__init__(message, status_code)
        self.path = path


class RequestTimeoutError(EzClassifyClientError, TimeoutError):
    """Raised when a request does not finish within the client's ``timeout``.

    The timeout is one deadline for the whole exchange: waiting for a pooled
    connection, connecting, the TLS handshake, sending the request, and
    reading the status, the headers and every byte of the body. A server that
    stalls, or trickles its answer, cannot hold a call past it. No response
    is kept, so ``status_code`` is ``0``. It is also a built-in
    ``TimeoutError``, and so an ``OSError``.

    Host name lookup is bounded by the system resolver, not this deadline.
    """


def _transport_error(exc: httpx.RequestError, path: str, timeout: float) -> Exception:
    """Turn an httpx transport failure into the client's own error."""
    if isinstance(exc, httpx.TimeoutException):
        return RequestTimeoutError(
            f"Request to {path} did not finish within {timeout:g}s: {exc}"
        )
    return EzClassifyClientError(f"Connection error: {exc}")


_BODY_EXCERPT_LIMIT = 200


def _excerpt(text: str) -> str:
    """Return a short, single-line excerpt of an unstructured response body."""
    flat = " ".join(text.split())
    if len(flat) <= _BODY_EXCERPT_LIMIT:
        return flat
    return flat[:_BODY_EXCERPT_LIMIT] + "..."


def _seconds(value: Any) -> float | None:
    """Read a wait in seconds, or ``None`` when it is not a usable one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _retry_after(
    response: httpx.Response, payload: Dict[str, Any] | None
) -> float | None:
    """Say how long a 429 asks the caller to wait.

    The ``Retry-After`` header and the body's ``retryAfter`` carry the same
    number; the header is preferred because a limiter in front of the server
    can answer without the JSON body. Any other status carries no wait.
    """
    if response.status_code != 429:
        return None
    header = _seconds(response.headers.get("Retry-After"))
    if header is not None:
        return header
    return _seconds(payload.get("retryAfter")) if payload else None


def _api_error(response: httpx.Response) -> EzClassifyClientError:
    """Preserve the stable JSON error contract from a non-success response."""
    try:
        raw = response.json()
    except ValueError:
        raw = None
    payload = raw if isinstance(raw, dict) else None
    code = payload.get("code") if payload else None
    detail = payload.get("detail") if payload else None
    message = (payload.get("error") or payload.get("message")) if payload else None
    # An unstructured body can be a whole document, and the exception string
    # reaches logs and crash reports, so the message carries a short excerpt.
    # The payload attribute holds the parsed JSON error object when there is
    # one; an unstructured body is not retained past the excerpt.
    summary = message or _excerpt(response.text)
    return EzClassifyClientError(
        f"REST API error {response.status_code}: {summary}",
        status_code=response.status_code,
        code=str(code) if code is not None else None,
        detail=str(detail) if detail is not None else None,
        payload=payload,
        retry_after=_retry_after(response, payload),
    )


def _decode_json(response: httpx.Response, op: str) -> Any:
    """Decode a success response body, or raise the client's own error type.

    Args:
        response: A 2xx response whose body is expected to be JSON.
        op: The request path or operation name, used in the error message.

    Returns:
        The decoded JSON value.

    Raises:
        MalformedResponseError: The body was not valid JSON. An intercepting
            proxy answering 200 with HTML is the common cause.
    """
    try:
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "unknown")
        raise MalformedResponseError(
            f"{op} answered {response.status_code} with a non-JSON body "
            f"(content-type: {content_type}): {_excerpt(response.text)}",
            response.status_code,
            path="$",
        ) from exc


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _json_path(tokens: Iterable[Union[str, int]]) -> str:
    """Spell a location in a body as JSONPath, from ``$`` for the root."""
    path = "$"
    for token in tokens:
        if isinstance(token, int):
            path += f"[{token}]"
        elif _IDENTIFIER.fullmatch(token):
            path += f".{token}"
        else:
            path += "['" + token.replace("\\", "\\\\").replace("'", "\\'") + "']"
    return path


def _located(value: Any, loc: Iterable[Union[str, int]]) -> List[Union[str, int]]:
    """Keep the steps of a validation ``loc`` that are members of ``value``.

    Pydantic names the arm of a union it tried among the member names, such
    as ``str`` or ``literal['a']``. Walking the body itself keeps the path to
    what the body holds; a step the body lacks is kept only when it is the
    last one, the member that is missing.
    """
    steps = list(loc)
    tokens: List[Union[str, int]] = []
    node = value
    for index, step in enumerate(steps):
        if isinstance(node, dict) and isinstance(step, str):
            if step not in node:
                if index == len(steps) - 1:
                    tokens.append(step)
                break
            tokens.append(step)
            node = node[step]
        elif isinstance(node, list) and isinstance(step, int) and step < len(node):
            tokens.append(step)
            node = node[step]
    return tokens


_Model = TypeVar("_Model", bound="_FromDict")


class _FromDict(Protocol):
    @classmethod
    def from_dict(cls: type[_Model], value: Dict[str, Any]) -> _Model: ...


def _decode_model(
    model: type[_Model],
    raw: Any,
    op: str,
    status: int,
    at: Tuple[Union[str, int], ...] = (),
) -> _Model:
    """Decode one success body as ``model``, strictly, or refuse it.

    ``from_dict`` checks every member the contract requires, at any depth,
    before the model validates. Anything it refuses becomes the client's own
    error, located in the body. ``at`` is where ``raw`` sits in the body, for
    an item of an array.

    Raises:
        MalformedResponseError: The body is not a JSON object, or is not the
            model the operation answers with.
    """
    if not isinstance(raw, dict):
        path = _json_path(at)
        raise MalformedResponseError(
            f"{op} answered {status} with {type(raw).__name__} at {path}, "
            "expected a JSON object",
            status,
            path=path,
        )
    try:
        return model.from_dict(raw)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        path = _json_path(at + tuple(_located(raw, first["loc"])))
        raise MalformedResponseError(
            f"{op} answered {status} with a body the contract does not allow at "
            f"{path}: {first['msg']}",
            status,
            path=path,
        ) from exc


def _decode_models(model: type[_Model], raw: Any, op: str, status: int) -> List[_Model]:
    """Decode a success body that is a JSON array of ``model``, or refuse it."""
    if not isinstance(raw, list):
        raise MalformedResponseError(
            f"{op} answered {status} with {type(raw).__name__}, expected a JSON array",
            status,
            path="$",
        )
    return [
        _decode_model(model, item, op, status, (index,))
        for index, item in enumerate(raw)
    ]


def _major_minor(version: str) -> str:
    """Return the ``major.minor`` prefix of a semantic version."""
    parts = version.split(".")
    return f"{parts[0]}.{parts[1] if len(parts) > 1 else '0'}"


@dataclass
class PingResult:
    """Health and build identity returned by the REST deployment."""

    engine_version: str
    engine_sha: str
    git_tag: str


@dataclass(frozen=True)
class RestClientCredentials:
    """Independent caller identity and Context authorization credentials.

    Args:
        access_token: Bearer token identifying the caller, or ``None``.
        context_token: Signed token authorizing Context operations, or ``None``.

    Raises:
        ValueError: If either supplied credential is blank.
    """

    access_token: str | None = None
    context_token: str | None = None

    def __post_init__(self) -> None:
        if self.access_token is not None and not self.access_token.strip():
            raise ValueError("access_token must be None or non-blank")
        if self.context_token is not None and not self.context_token.strip():
            raise ValueError("context_token must be None or non-blank")


def _validate_application_credential(
    headers: Dict[str, str], credentials: RestClientCredentials
) -> str | None:
    """Validate the opaque application auth mode before creating a transport."""
    if any(not isinstance(name, str) for name in headers):
        raise ValueError("HTTP header names must be strings")
    application_headers = [
        name for name in headers if name.lower() == "x-ezclassify-application-grant"
    ]
    if not application_headers:
        return None
    if (
        len(application_headers) != 1
        or credentials.context_token is not None
        or any(
            name.lower() in {"authorization", "x-ezclassify-context-token"}
            for name in headers
        )
    ):
        raise ValueError(
            "An application credential requires one header and cannot be combined "
            "with Context tokens or an explicit Authorization header; supply a "
            "user bearer through RestClientCredentials.access_token"
        )
    name = application_headers[0]
    value = headers[name]
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) >= 127 for character in value)
    ):
        raise ValueError(
            "An application credential must be nonempty printable ASCII without "
            "leading or trailing whitespace"
        )
    return name


class EzClassifyClient:
    """A deployment client for discovery, health, and Context binding.

    This surface cannot classify against a loose scheme. Remote evaluation is
    always bound to a published Context so the exact scheme, layers, guides,
    access policy, and crosswalk set are resolved together.

    ``timeout`` is the most time, in seconds, any one call may take from start
    to finish, the whole response body included. A call that runs out raises
    :class:`RequestTimeoutError`.

    Supply an opaque managed application credential through
    ``headers={"X-EzClassify-Application-Grant": credential}``. It is sent only
    on Context routes, never health probes. Supply the current user's bearer
    through ``RestClientCredentials.access_token`` when the application's user
    policy requires it. Context token credentials cannot accompany the grant.
    The Runtime verifies both credentials under the configured policy.

    Raises:
        TypeError: ``timeout`` is not a number.
        ValueError: ``timeout`` is not positive and finite, or an application
            credential is empty, malformed, duplicated or mixed with Context
            credentials or an explicit Authorization header.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        headers: Dict[str, str] | None = None,
        credentials: RestClientCredentials | None = None,
    ) -> None:
        self._timeout = require_timeout(timeout)
        self._base = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self._credentials = credentials or RestClientCredentials()
        self._application_header = _validate_application_credential(
            self._headers, self._credentials
        )
        self._client = httpx.Client(
            base_url=self._base,
            timeout=self._timeout,
            transport=deadline_transport(self._base),
        )
        self._version_warn_emitted = False

    def _get(self, path: str, model: type[_Model], op: str) -> _Model:
        """Send one discovery or health read and decode it strictly as ``model``."""
        try:
            with request_deadline(self._timeout):
                response = self._client.get(path, headers=self._request_headers(path))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _api_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise _transport_error(exc, path, self._timeout) from exc
        return _decode_model(
            model, _decode_json(response, op), op, response.status_code
        )

    def _request_headers(self, path: str) -> Dict[str, str]:
        """Build route-specific headers without leaking Context authorization."""
        headers = dict(self._headers)
        if self._credentials.access_token is not None:
            headers["Authorization"] = f"Bearer {self._credentials.access_token}"
        if path == "/v1/ctx" or path.startswith("/v1/ctx/"):
            if self._credentials.context_token is not None:
                headers["x-ezclassify-context-token"] = self._credentials.context_token
        elif self._application_header is not None:
            del headers[self._application_header]
        return headers

    def list_contexts(self) -> List[str]:
        """List the Context ids visible to the caller.

        Raises:
            MalformedResponseError: The answer is not the list the contract
                describes.
            EzClassifyClientError: The server refused the request or could not
                be reached. A 429 carries ``retry_after``.
        """
        return self._get("/v1/ctx", _CtxListResponseBody, "context discovery").contexts

    def list_context_versions(self, context_id: str) -> List[str]:
        """List installed versions for one Context, highest version first.

        Raises:
            ValueError: ``context_id`` is blank or a dot segment.
            MalformedResponseError: The answer is not the list the contract
                describes.
            EzClassifyClientError: The server refused the request or could not
                be reached. A 429 carries ``retry_after``.
        """
        if not context_id or not context_id.strip() or context_id in {".", ".."}:
            raise ValueError("context_id must not be blank or a dot segment")
        path = f"/v1/ctx/{quote(context_id, safe='')}"
        body = self._get(path, _CtxVersionsResponseBody, "context version discovery")
        return body.versions

    def context(
        self,
        context_id: str,
        context_version: str | None = None,
        *,
        cache_access_decisions: bool = False,
        disable_cache: bool = False,
    ) -> "EzClassifyContext":
        """Resolve and return an operation client bound to one Context.

        Omit ``context_version`` to let the server choose: the default version
        of the signed context token in this client's credentials, or the
        newest published version when there is no token. ``"latest"`` asks
        for the same thing by name; a concrete version pins the binding.

        The returned handle owns its own connection pool, and the caller owns
        the handle: close it, or use it as a context manager. Closing this
        deployment client does not close handles it has handed out. Access
        decisions are uncached by default so every call leaves a server audit
        record. ``cache_access_decisions=True`` requires a concrete version
        and trades those records for fewer requests. ``disable_cache=True``
        sends every operation to the server.

        Raises:
            ValueError: A blank or dot-segment ``context_id``, a ``context_version``
                that is only whitespace or a dot segment, or ``cache_access_decisions`` on an unpinned
                binding.
            MalformedResponseError: The Context description is not the one
                the contract describes.
            RequestTimeoutError: The description did not arrive within this
                client's ``timeout``.
            EzClassifyClientError: The server refused the request or could not
                be reached. A 429 carries ``retry_after``.
        """
        from .context import connect_context

        return connect_context(
            self._base,
            context_id=context_id,
            context_version=context_version,
            timeout=self._timeout,
            headers=self._headers,
            credentials=self._credentials,
            cache_access_decisions=cache_access_decisions,
            disable_cache=disable_cache,
        )

    def engine_spec_version(self) -> str:
        """Return the wire-contract version this client was generated against."""
        return CLIENT_SPEC_VERSION

    def ping(self) -> PingResult:
        """Read deployment health and warn once on an engine minor mismatch.

        Returns:
            The engine version, build SHA, and tag the deployment reports.

        Raises:
            MalformedResponseError: The answer is not the health report the
                contract describes.
            EzClassifyClientError: The server refused the request or could not
                be reached. A 429 carries ``retry_after``.
        """
        body = self._get("/v1/health", _HealthResponse, "health")
        result = PingResult(
            engine_version=body.engine_version,
            engine_sha=body.engine_sha,
            git_tag=body.git_tag,
        )
        if not self._version_warn_emitted and _major_minor(
            CLIENT_SPEC_VERSION
        ) != _major_minor(result.engine_version):
            # Imported here, not at module scope, because the package __init__
            # that computes __version__ imports this module.
            from . import __version__

            self._version_warn_emitted = True
            logger.warning(
                "ezclassify-rest-client v%s is intended for rest-api v%s; connected to v%s",
                __version__,
                CLIENT_SPEC_VERSION,
                result.engine_version,
            )
        return result

    def close(self) -> None:
        """Close this client's connection pool.

        Context handles returned by :meth:`context` own separate pools and are
        closed by their own caller.
        """
        self._client.close()

    def __enter__(self) -> "EzClassifyClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


if TYPE_CHECKING:
    from .context import EzClassifyContext
