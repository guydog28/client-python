"""Context-bound client surface for the EzClassify REST API.

``connect_context`` returns an :class:`EzClassifyContext` bound to one named,
versioned Context. Every operation routes through
``/v1/ctx/{context_id}/{version}/*``. The path selects the composed bundle
(scheme + layers + guides + access policy), so request bodies carry payload only.

Example::

    from ezclassify_rest_client import connect_context

    ctx = connect_context("http://localhost:3000", context_id="my-ctx", context_version="1.0.0")
    result = ctx.scheme.validate("MARKING")
    print(ctx.resolved_version)  # concrete version the server resolved
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, overload
from urllib.parse import quote

import httpx

from ._deadline import deadline_transport, request_deadline, require_timeout
from ._response_cache import ResponseCache
from .client import (
    MalformedResponseError,
    RestClientCredentials,
    _api_error,
    APPLICATION_ID_HEADER,
    validate_application_id,
    _decode_json,
    _decode_model,
    _decode_models,
    _json_path,
    _Model,
    _transport_error,
)
from .models import (
    Assertion,
    ContextDocumentAuditResult,
    ContextAccessDecisionResult,
    ContextAccessRequirementsResult,
    ContextCrosswalkTranslationResult,
    ContextGuideEvaluationResult,
    ContextGuideScanResult,
    ContextGuideViewResult,
    ContextSchemeAggregateResult,
    ContextSchemeConceptDescriptionResult,
    ContextSchemeCoverageResult,
    ContextSchemeDiffResult,
    ContextSchemeExplainResult,
    ContextSchemeNoticesResult,
    ContextSchemeProcessResult,
    ContextSchemeRenderResult,
    ContextSchemeScanResult,
    ContextSchemeSuggestForCategoriesResult,
    ContextSchemeSuggestResult,
    ContextSchemeValidateResult,
    ContextSchemeViewResult,
    GuideDeterminationInput,
    CategoryView,
    ConceptView,
    ContextDescription,
    CtxAccessRulesResponseBody,
    CtxCrosswalkDescribeResponseBody,
    GuideRuleSelection,
    FormatView,
    LabelPresetView,
    SchemeScope,
    SchemeSummary,
)

_RESOLVED_VERSION_HEADER = "X-EzClassify-Resolved-Version"

# The operations whose answers the response cache keeps. explain posts the
# same body process does, to its own route, so the two never share an entry.
# access/check is never among them: every decision reaches the server so the
# deployment records it.
_CACHED_POSTS = frozenset(
    {
        "scheme/process",
        "scheme/validate",
        "scheme/explain",
        "scheme/render",
        "scheme/diff",
        "scheme/aggregate",
        "scheme/apply-preset",
        "scheme/suggest",
        "scheme/suggest-for-categories",
        "scheme/scan",
    }
)
_CACHED_GETS = frozenset(
    {"scheme/describe-concept", "access/rules", "crosswalk/describe"}
)

# A response check the result model cannot express, given the decoded body
# and its status. It raises MalformedResponseError.
_Check = Callable[[Dict[str, Any], int], None]

# The body a deployment running authentication answers every unauthenticated
# request with. Authentication runs before routing, so the runtime cannot say
# more without revealing which routes exist; a genuine not-found that names
# the missing thing carries other members and is not this.
_DENIAL_BODY = {"error": "not_found"}


def _refuses_the_caller(response: httpx.Response) -> bool:
    """Say whether an error response refuses the caller rather than the request.

    That is an explicit 401, or a 404 whose body is exactly the runtime's
    constant denial. Held answers were computed for a caller the server no
    longer accepts, so they must not outlive either one. Any other 404 is
    about the resource and leaves the cache alone.
    """
    if response.status_code == 401:
        return True
    if response.status_code != 404:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return bool(body == _DENIAL_BODY)


def _assertion_to_wire(a: Assertion) -> Dict[str, Any]:
    """Project an assertion to the camelCase wire shape the engine expects.

    Serializes every populated field, not just the required quartet, so an
    assertion round-trips through the ctx surface unchanged. Dropping a field
    would break the lossless transport contract on ``aggregate_assertions``.
    """
    return a.model_dump(mode="json", by_alias=True, exclude_none=True)


def _put_if_set(body: Dict[str, Any], wire_name: str, value: Optional[str]) -> None:
    """Set an optional body field under its wire name when the caller gave one.

    Leaving the key off the wire, rather than sending ``null``, keeps the
    server on its documented default for that field.
    """
    if value is not None:
        body[wire_name] = value


def _put_value_if_set(body: Dict[str, Any], wire_name: str, value: Any) -> None:
    """Set an optional non-string body field when the caller gave one.

    The same rule as :func:`_put_if_set` for booleans and objects: ``None``
    leaves the key off so the server applies its default, while ``False`` is a
    real answer and is sent.
    """
    if value is not None:
        body[wire_name] = value


def _put_assertions_if_set(
    body: Dict[str, Any], assertions: Optional[List[Assertion]]
) -> None:
    """Set the optional ``assertions`` field in its camelCase wire shape."""
    if assertions is not None:
        body["assertions"] = [_assertion_to_wire(a) for a in assertions]


def connect_context(
    base_url: str,
    *,
    context_id: str,
    context_version: str | None = None,
    timeout: float = 30.0,
    headers: Dict[str, str] | None = None,
    credentials: RestClientCredentials | None = None,
    application_id: str | None = None,
    disable_cache: bool = False,
) -> "EzClassifyContext":
    """Connect to a named Context and return a bound client.

    Omit ``context_version`` to let the server choose: the default version of
    the signed context token in ``credentials``, or the newest published
    version when there is no token. ``"latest"`` asks for the same thing by
    name, and an empty string means the same as omitting it. A concrete
    version such as ``"1.0.0"`` pins the binding. Whichever version the server
    resolves is read from the ``X-EzClassify-Resolved-Version`` response
    header and exposed via :attr:`EzClassifyContext.resolved_version`. This
    call checks the binding against the Context description before returning.

    Access decisions are never cached: every call reaches the server, so the
    deployment records each audit decision.

    ``timeout`` is the most time, in seconds, any one request may take from
    start to finish, the whole response body included; this call's own
    request included. ``application_id`` names the calling application, the id it
    is registered under in Studio. It is sent as the
    ``x-ezclassify-application-id`` header on every Context request so the deployment
    can report usage per application. It is not a credential and authorizes
    nothing.

    Raises:
        TypeError: ``timeout`` is not a number.
        ValueError: ``context_id`` is blank or a dot segment, ``context_version`` is
            only whitespace or a dot segment, ``timeout`` is not positive and
            finite, or ``application_id`` is not 1 to 128 characters of
            printable ASCII from ``!`` to ``~``.
        MalformedResponseError: The Context description is not the one the
            contract describes.
        RequestTimeoutError: The description did not arrive within
            ``timeout``.
        EzClassifyClientError: The server refused the request or could not be
            reached. A 429 carries ``retry_after``.
    """
    ctx = EzClassifyContext(
        base_url,
        context_id=context_id,
        context_version=context_version,
        timeout=timeout,
        headers=headers,
        credentials=credentials,
        application_id=application_id,
        disable_cache=disable_cache,
    )
    try:
        ctx.resolve()
    except BaseException:
        # The handle is never returned, so release its connection pool
        # instead of leaving the httpx client open until GC.
        ctx.close()
        raise
    return ctx


class EzClassifyContext:
    """A handle bound to one named Context.

    Reach the operations through :attr:`scheme`, :attr:`guide`, :attr:`access`,
    :attr:`document`, and :attr:`crosswalk`. :attr:`scheme` addresses the
    Context's primary scheme; :attr:`schemes` reaches any other scheme it
    holds, by key. The context is synchronous and safe to use as a context
    manager.

    A concrete ``context_version`` pins the binding: a published Context
    version is immutable, so its answers are kept until the handle closes or
    :meth:`clear_cache`. An omitted version, where the server chooses (the
    context token's default, or the newest published), and ``"latest"`` are
    unpinned: answers expire, and a response naming another resolved version
    drops them.

    Every operation raises :class:`MalformedResponseError` for a success the
    contract does not allow, :class:`EzClassifyClientError` for a refusal or a
    failed connection (a 429 carries ``retry_after``), and ``ValueError`` only
    for its own arguments.

    ``timeout`` is the most time, in seconds, any one request may take from
    start to finish, the whole response body included. A request that runs
    out raises :class:`RequestTimeoutError`, an :class:`EzClassifyClientError`.
    A call answered from the cache makes no request; one that joins a request
    already in flight for the same answer waits only as long as that request
    may run.

    Raises:
        TypeError: ``timeout`` is not a number.
        ValueError: ``context_id`` is blank or a dot segment, ``context_version`` is
            only whitespace or a dot segment, ``timeout`` is not positive and
            finite, or ``application_id`` is not 1 to 128 characters of
            printable ASCII from ``!`` to ``~``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        context_id: str,
        context_version: str | None = None,
        timeout: float = 30.0,
        headers: Dict[str, str] | None = None,
        credentials: RestClientCredentials | None = None,
        application_id: str | None = None,
        disable_cache: bool = False,
    ) -> None:
        if not context_id or not context_id.strip() or context_id in {".", ".."}:
            raise ValueError("context_id must not be blank or a dot segment")
        self._timeout = require_timeout(timeout)
        if context_version == "":
            context_version = None
        if context_version is not None and (
            not context_version.strip() or context_version in {".", ".."}
        ):
            raise ValueError(
                "context_version must not be only whitespace or a dot segment"
            )
        resolved_credentials = credentials or RestClientCredentials()
        self._base = base_url.rstrip("/")
        self._context_id = context_id
        self._version = context_version
        request_headers = dict(headers or {})
        if application_id is not None:
            request_headers[APPLICATION_ID_HEADER] = validate_application_id(
                application_id
            )
        if resolved_credentials.access_token is not None:
            request_headers["Authorization"] = (
                f"Bearer {resolved_credentials.access_token}"
            )
        if resolved_credentials.context_token is not None:
            request_headers["x-ezclassify-context-token"] = (
                resolved_credentials.context_token
            )
        self._client = httpx.Client(
            base_url=self._base,
            timeout=self._timeout,
            headers=request_headers,
            transport=deadline_transport(self._base),
        )
        self._response_cache = ResponseCache()
        self._disable_cache = disable_cache
        self._resolved_version: Optional[str] = None
        self.scheme = CtxScheme(self)
        self.schemes = CtxSchemes(self)
        self.guide = CtxGuide(self)
        self.access = CtxAccess(self)
        self.document = CtxDocument(self)
        self.crosswalk = CtxCrosswalk(self)

    @property
    def context_id(self) -> str:
        """The context identifier this handle is bound to."""
        return self._context_id

    @property
    def version(self) -> Optional[str]:
        """The version segment used in request paths.

        A concrete version, ``"latest"``, or ``None`` when the version was
        omitted, so the server chooses it and operation paths carry no
        version segment.
        """
        return self._version

    @property
    def resolved_version(self) -> Optional[str]:
        """Concrete version the server last resolved this context to, or ``None``.

        Read from the ``X-EzClassify-Resolved-Version`` response header; populated
        by :meth:`resolve` (which ``connect_context`` runs) and updated whenever
        a server response supplies that header. A cache hit makes no request
        and retains the last observed version.
        """
        return self._resolved_version

    def clear_cache(self) -> None:
        """Discard cached operation responses without dropping the Context binding."""
        self._response_cache.clear()

    def resolve(self) -> None:
        """Check the binding against the Context description and capture its resolved version.

        Raises:
            MalformedResponseError: The description is not the one the
                contract describes.
            EzClassifyClientError: The server refused the binding or could not
                be reached. A 429 carries ``retry_after``.
        """
        self.describe()

    def describe(self) -> ContextDescription:
        """Describe what the bound Context resolves to right now.

        This is the record an audit trail keeps beside a decision: the
        composed scheme with the layers stacked on it, the guides in
        precedence order, the access policy, and the crosswalks in
        declaration order. Each component reports the version the Context
        declares (``version``, possibly ``"latest"``) beside the concrete one
        that answered (``resolved_version``). ``schemes`` lists every scheme
        the Context holds with the selector that addresses it.

        Every call makes one request, so the answer is current. It is not
        kept in the response cache, and :meth:`clear_cache` has nothing to
        drop for it. Hold the result when you need it again.

        Returns:
            The typed description. ``guides`` and ``crosswalks`` are empty
            when the Context declares none, and ``access`` is ``None``.

        Raises:
            MalformedResponseError: The server answered with a body that is
                not a Context description.
            EzClassifyClientError: The server refused the request or could not
                be reached. A 429 carries ``retry_after``.
        """
        return self._get("", ContextDescription)

    @property
    def _pinned(self) -> bool:
        """Whether the binding names a published, immutable Context version."""
        return self._version is not None and self._version != "latest"

    def _op_path(self, op: str) -> str:
        """Build the request path for an operation, or for the Context itself.

        A binding with no version sends no version segment, so the server
        chooses: the context token's default version, or the newest published.
        The Context description is the exception: without a version segment
        that URL lists the Context's versions instead, so the description is
        asked for at ``latest``, which the server resolves the same way.
        """
        base = f"/v1/ctx/{quote(self._context_id, safe='')}"
        version = self._version
        if version is None and not op:
            version = "latest"
        if version is not None:
            base = f"{base}/{quote(version, safe='')}"
        return base if not op else f"{base}/{op}"

    def _describe(self, op: str) -> str:
        """Name an operation for error messages: context id plus operation path."""
        return f"context {self._context_id} operation {op or 'describe'}"

    def _capture(self, response: httpx.Response, keep_key: str | None = None) -> None:
        resolved = response.headers.get(_RESOLVED_VERSION_HEADER)
        if resolved:
            if (
                self._resolved_version is not None
                and resolved != self._resolved_version
            ):
                self._response_cache.clear(keep_key)
            self._resolved_version = resolved

    def _cache_ttl(self, op: str) -> float:
        """Say how long an answer stays valid: forever when pinned, else an hour at most."""
        if self._pinned:
            return float("inf")
        if op == "scheme/scan":
            return 120.0
        if op in {"scheme/describe-concept", "access/rules", "crosswalk/describe"}:
            return 3600.0
        return 300.0

    def _cache_key(
        self,
        method: str,
        op: str,
        body: Dict[str, Any] | None,
        params: Dict[str, Any] | None = None,
    ) -> str:
        return json.dumps(
            [method, self._context_id, self._version, op, body, params],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def _caches(self, method: str, op: str) -> bool:
        """Whether this binding keeps answers to ``op``."""
        if self._disable_cache:
            return False
        if method == "GET":
            return op in _CACHED_GETS
        return op in _CACHED_POSTS

    def _post(
        self,
        op: str,
        body: Dict[str, Any],
        model: type[_Model],
        check: _Check | None = None,
        params: Dict[str, Any] | None = None,
    ) -> _Model:
        """Send one operation and decode its answer, through the cache when cached.

        A POST operation takes its input in the body. The only query one
        carries is the scheme key a scheme view adds; every other caller
        passes no ``params``, and the server refuses a query parameter an
        operation does not declare. The scheme's key is part of the cache
        key, so two schemes never share an answer.

        ``check`` is a response check the result model cannot express, such as
        a map that must answer every key the request named. It runs on every
        answer, and inside the cached read, so a malformed answer raises for
        this caller and is never kept for the next one.
        """
        return self._operation("POST", op, model, body=body, params=params, check=check)

    def _get(
        self, op: str, model: type[_Model], params: Dict[str, Any] | None = None
    ) -> _Model:
        """Read one Context resource and decode it, through the cache when cached."""
        return self._operation("GET", op, model, params=params)

    def _get_list(
        self, op: str, model: type[_Model], params: Dict[str, Any] | None = None
    ) -> List[_Model]:
        """Read a Context resource that answers a JSON array of ``model``.

        None of these is cached: the scheme resources are read once by a
        caller that builds a picker or a form, and kept there.
        """
        raw, status = self._send("GET", op, params=params)
        return _decode_models(model, raw, self._describe(op), status)

    def _operation(
        self,
        method: str,
        op: str,
        model: type[_Model],
        *,
        body: Dict[str, Any] | None = None,
        params: Dict[str, Any] | None = None,
        check: _Check | None = None,
    ) -> _Model:
        def read(cache_key: str | None) -> Tuple[Dict[str, Any], _Model]:
            raw, status = self._send(
                method, op, body=body, params=params, cache_key=cache_key
            )
            decoded = _decode_model(model, raw, self._describe(op), status)
            if check is not None:
                check(raw, status)
            return raw, decoded

        if not self._caches(method, op):
            return read(None)[1]
        key = self._cache_key(method, op, body, params)
        # The cache keeps only an answer that decoded, so a malformed one
        # raises for this caller and the next one asks the server again.
        held = self._response_cache.get(key, self._cache_ttl(op), lambda: read(key)[0])
        return model.from_dict(self._independent(held))

    @staticmethod
    def _independent(held: Any) -> Any:
        """Hand a caller its own copy of a cached or shared answer.

        Callers that joined one request, and later callers served from the
        entry, would otherwise share the nested lists and dictionaries a
        model keeps as opaque JSON. Mutating one caller's result must not
        change what another holds or what the next cached read returns.
        """
        return copy.deepcopy(held)

    def _send(
        self,
        method: str,
        op: str,
        *,
        body: Dict[str, Any] | None = None,
        params: Dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> Tuple[Any, int]:
        """Send one request and return its decoded JSON body and status."""
        path = self._op_path(op)
        try:
            with request_deadline(self._timeout):
                if method == "POST":
                    response = self._client.post(path, json=body, params=params)
                else:
                    response = self._client.get(path, params=params)
            self._capture(response, cache_key)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _refuses_the_caller(exc.response):
                self._response_cache.clear()
            raise _api_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise _transport_error(exc, path, self._timeout) from exc
        return _decode_json(response, self._describe(op)), response.status_code

    def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        self._response_cache.clear()
        self._client.close()

    def __enter__(self) -> "EzClassifyContext":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class CtxScheme:
    """Scheme-domain operations bound to one scheme of a :class:`EzClassifyContext`.

    ``ctx.scheme`` is bound to the Context's primary scheme and addresses it
    by leaving the ``scheme`` query off the wire. A view from
    :meth:`CtxSchemes.get` is bound to the scheme its key names and sends that
    key as ``?scheme=`` on every operation and read it makes. The operations
    take no key of their own: the view picks the scheme, so one call cannot
    address a scheme other than its view's.
    """

    def __init__(self, ctx: EzClassifyContext, key: Optional[str] = None) -> None:
        self._ctx = ctx
        self._key = key

    def _query(self, params: Dict[str, Any] | None = None) -> Optional[Dict[str, Any]]:
        """Add this view's scheme key to an operation's query.

        The primary view adds nothing, so its requests carry no ``scheme``
        parameter at all rather than an empty one.
        """
        if self._key is None:
            return params
        return {**(params or {}), "scheme": self._key}

    def _post(
        self,
        op: str,
        body: Dict[str, Any],
        model: type[_Model],
        check: _Check | None = None,
    ) -> _Model:
        return self._ctx._post(op, body, model, check=check, params=self._query())

    def _get(
        self, op: str, model: type[_Model], params: Dict[str, Any] | None = None
    ) -> _Model:
        return self._ctx._get(op, model, self._query(params))

    def _get_list(self, op: str, model: type[_Model]) -> List[_Model]:
        return self._ctx._get_list(op, model, self._query())

    def process(
        self,
        marking: str,
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        assertions: List[Assertion] | None = None,
        context: Dict[str, Any] | None = None,
        parts: List[str] | None = None,
        outputs: List[str] | None = None,
        suggest_for: List[str] | None = None,
    ) -> ContextSchemeProcessResult:
        """Process a marking for someone writing it: the author's call.

        ``marking`` is what was typed and ``assertions`` the facts already
        chosen. The two are settled together as one marking, which is what a
        composer sends on each keystroke. Pass an empty ``marking`` with
        ``assertions`` to process the chosen facts alone.

        The result carries everything :meth:`validate` answers, settled the
        same way, plus what an author needs to correct and finish the marking:
        the corrections that turn the text into canonical text, in
        ``recognition["corrections"]``, what was read before repair, and the
        proposed fixes, each a whole marking the engine has proven. ``renders``
        holds a rendering for each output named in ``outputs`` and nothing
        else. ``suggestions_for`` is present only when ``suggest_for`` names
        categories. A caller that only reads a marking calls :meth:`validate`,
        and the trace of how the engine got here is :meth:`explain`.

        Args:
            marking: The marking text, as typed. May be empty when
                ``assertions`` carries the marking.
            output_format: Optional output ``rendered`` is written in: a
                format id, or for a scheme that declares surfaces a view id,
                a ``surface/view`` address, or the id of a form exactly one
                view names. It selects output only and never narrows what
                may be read. Omitted, the scheme's default format, or for a
                scheme that declares surfaces, each surface the result
                writes in its default view for the marking's role.
            surface: Optional validation surface, named with one of the
                scheme's scope ids. Omitted, the marking is evaluated as a
                whole.
            input_format: Optional format the input is written in. For a
                scheme that declares surfaces, a view id, a ``surface/view``
                address, or the id of one of a view's forms. Omitted,
                recognition works it out, and ``recognition["inputFormat"]``
                reports what the text was read as.
            assertions: Optional facts already chosen, settled together with
                what ``marking`` states.
            context: Optional processing context, forwarded verbatim to the
                engine. ``{"role": "part", "partOf": {"rendered": ...}}``
                marks the input as a portion of the given whole marking. A
                role given here is the role the marking is judged and written
                in. Omitted, the role is the one recognition decides for the
                text, reported in ``recognition["role"]``, and a marking with
                no role is written as a whole.
            parts: Part markings the whole must cover. The whole is judged as
                covering them: a part it does not cover is an error, and so is
                a part that does not read as a marking. Every rank floor and
                every proposed fix is worked out against the whole and these
                parts together, so a raise never lands below what a part
                needs. Each entry is a marking in one of the scheme's part
                formats, or any format the scheme reads. Empty or absent, the
                whole stands alone.
            outputs: Outputs to write into ``renders``, each spelled exactly as
                a key of ``renders`` is: ``surface/view`` for a scheme that
                declares surfaces, a format id otherwise. Omitted or empty,
                ``renders`` is empty. An output the scheme does not declare is
                refused.
            suggest_for: Category ids to answer picker options for, against
                the settled facts, in ``suggestions_for``. Omitted, nothing is
                suggested and ``suggestions_for`` is ``None``. A category the
                scheme does not declare is refused.
        """
        body: Dict[str, Any] = {"input": marking}
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_assertions_if_set(body, assertions)
        _put_value_if_set(body, "context", context)
        _put_value_if_set(body, "parts", parts)
        _put_value_if_set(body, "outputs", outputs)
        _put_value_if_set(body, "suggestFor", suggest_for)
        return self._post("scheme/process", body, ContextSchemeProcessResult)

    # The two spellings of validate, so a type checker refuses a call that
    # gives neither or both before it runs. The implementation below still
    # checks, for callers that are not type-checked.
    @overload
    def validate(
        self,
        marking: str,
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        context: Dict[str, Any] | None = None,
        parts: List[str] | None = None,
    ) -> ContextSchemeValidateResult: ...

    @overload
    def validate(
        self,
        *,
        assertions: List[Assertion],
        output_format: str | None = None,
        surface: str | None = None,
        context: Dict[str, Any] | None = None,
        parts: List[str] | None = None,
    ) -> ContextSchemeValidateResult: ...

    def validate(
        self,
        marking: str | None = None,
        *,
        assertions: List[Assertion] | None = None,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        context: Dict[str, Any] | None = None,
        parts: List[str] | None = None,
    ) -> ContextSchemeValidateResult:
        """Judge a marking for someone reading it: the reader's call.

        Call it to display a marking, gate on it, store it, or hand its facts
        to an access check or a rollup. The marking is text in ``marking`` or
        facts in ``assertions``, exactly one of the two. Facts here are what a
        document or an author states before any engine has settled them, never
        the ``assertions`` of an earlier result: those are settled already and
        can read valid where the text they came from did not.

        The server settles the marking exactly as :meth:`process` does, so
        ``valid`` (the marking stands once settled) and ``input_was_valid`` (it
        was right as written) mean the same on both. The result is the settled
        facts, those two verdicts, errors and warnings, the changes settling
        made, the marking written back with its assessment, how recognition
        read it, the notices and the display color. Fix paths and corrections
        to the text are an author's concern and come from :meth:`process`.

        Args:
            marking: The marking as text. Give this or ``assertions``, never
                both.
            assertions: The marking as facts as stated. Give this or
                ``marking``, never both.
            output_format: Optional output ``rendered`` is written in: a
                format id, or for a scheme that declares surfaces a view id,
                a ``surface/view`` address, or the id of a form exactly one
                view names. It selects output only and never narrows what
                may be read. Omitted, the scheme's default format, or for a
                scheme that declares surfaces, each surface the result
                writes in its default view for the marking's role.
            surface: Optional validation surface, named with one of the
                scheme's scope ids. Omitted, the marking is evaluated as a
                whole.
            input_format: Optional format ``marking`` is written in. For a
                scheme that declares surfaces, a view id, a ``surface/view``
                address, or the id of one of a view's forms. Omitted,
                recognition works it out, and ``recognition["inputFormat"]``
                reports what the text was read as. It cannot accompany
                ``assertions``, which carry no text.
            context: Optional processing context, forwarded verbatim to the
                engine. ``{"role": "part", "partOf": {"rendered": ...}}``
                marks the input as a portion of the given whole marking. A
                role given here is the role the marking is judged and written
                in. Omitted, the role is the one recognition decides for the
                text, reported in ``recognition["role"]``, and a marking with
                no role is written as a whole.
            parts: Part markings the whole must cover. The whole is judged as
                covering them: a part it does not cover is an error, and so is
                a part that does not read as a marking. Each entry is a
                marking in one of the scheme's part formats, or any format the
                scheme reads. Empty or absent, the whole stands alone.

        Raises:
            ValueError: Neither or both of ``marking`` and ``assertions`` were
                given, or ``input_format`` accompanies facts.
        """
        if (marking is None) == (assertions is None):
            raise ValueError("provide exactly one of marking or assertions")
        if assertions is not None and input_format is not None:
            raise ValueError("input_format is only valid with marking text")
        body: Dict[str, Any] = {}
        _put_if_set(body, "input", marking)
        _put_assertions_if_set(body, assertions)
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_value_if_set(body, "context", context)
        _put_value_if_set(body, "parts", parts)
        return self._post("scheme/validate", body, ContextSchemeValidateResult)

    def explain(
        self,
        marking: str,
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        assertions: List[Assertion] | None = None,
        context: Dict[str, Any] | None = None,
        parts: List[str] | None = None,
    ) -> ContextSchemeExplainResult:
        """Explain, step by step, how the server settles a marking.

        Takes what :meth:`process` takes apart from ``outputs`` and
        ``suggest_for``, which only add to a process result, and returns the
        trace of that same processing: what was read, repaired, inferred and
        found wrong, and what was written. Reach for it when someone wants to
        know why a marking came out the way it did. No other operation
        returns the trace.

        Args:
            marking: The marking text, as typed. May be empty when
                ``assertions`` carries the marking.
            output_format: Optional output the trace's ``rendered`` is written
                in: a format id, or for a scheme that declares surfaces a view
                id, a ``surface/view`` address, or the id of a form exactly
                one view names. Omitted, the scheme's default format, or for
                a scheme that declares surfaces, each surface the result
                writes in its default view for the marking's role.
            surface: Optional validation surface, named with one of the
                scheme's scope ids. Omitted, the marking is evaluated as a
                whole.
            input_format: Optional format the input is written in, as on
                :meth:`process`. Omitted, recognition works it out.
            assertions: Optional facts already chosen, settled together with
                what ``marking`` states.
            context: Optional processing context, forwarded verbatim to the
                engine, as on :meth:`process`.
            parts: Part markings the whole must cover, judged as on
                :meth:`process`.
        """
        body: Dict[str, Any] = {"input": marking}
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_assertions_if_set(body, assertions)
        _put_value_if_set(body, "context", context)
        _put_value_if_set(body, "parts", parts)
        return self._post("scheme/explain", body, ContextSchemeExplainResult)

    @overload
    def suggest(
        self,
        partial: str,
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        filter: str | None = None,
        include_gated: bool | None = None,
    ) -> ContextSchemeSuggestResult: ...

    @overload
    def suggest(
        self,
        *,
        assertions: List[Assertion],
        output_format: str | None = None,
        surface: str | None = None,
        filter: str | None = None,
        include_gated: bool | None = None,
    ) -> ContextSchemeSuggestResult: ...

    def suggest(
        self,
        partial: str | None = None,
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        filter: str | None = None,
        assertions: List[Assertion] | None = None,
        include_gated: bool | None = None,
    ) -> ContextSchemeSuggestResult:
        """Picker options for text or stated facts, exactly one of the two.

        How the marking reads and whether it stands are what :meth:`validate`
        and :meth:`process` answer, and suggest does not repeat them. An
        author who is processing the marking anyway gets options in the same
        round trip by naming categories in ``suggest_for`` on
        :meth:`process`.

        Args:
            partial: Partial marking string to complete. Give this or
                ``assertions``, never both. Empty text is a valid input.
            output_format: Optional format the suggestion previews are
                rendered in: a format id, or for a scheme that declares
                surfaces a view id, a ``surface/view`` address, or the id of
                a form exactly one view names.
            surface: Optional validation surface, named with one of the
                scheme's scope ids. Omitted, the marking is evaluated as a
                whole.
            input_format: Optional format the input is written in. Omitted,
                recognition works it out. It cannot accompany facts.
            filter: Optional filter string that narrows the suggestions.
            assertions: Stated facts used as the suggestion baseline. Give
                this or ``partial``, never both. An empty list is a valid input.
            include_gated: When true, also return concepts the filter would
                hide because their prerequisites are unmet. Each comes back
                with ``gated`` set and the ``requires`` ids that unlock it.

        Raises:
            ValueError: Neither or both inputs were given, or ``input_format``
                accompanies facts.
        """
        if (partial is None) == (assertions is None):
            raise ValueError("provide exactly one of partial or assertions")
        if assertions is not None and input_format is not None:
            raise ValueError("input_format is only valid with partial text")
        body: Dict[str, Any] = {}
        _put_if_set(body, "input", partial)
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_if_set(body, "filter", filter)
        _put_assertions_if_set(body, assertions)
        _put_value_if_set(body, "includeGated", include_gated)
        return self._post("scheme/suggest", body, ContextSchemeSuggestResult)

    def suggest_for_categories(
        self,
        assertions: List[Assertion],
        category_ids: List[str],
        *,
        output_format: str | None = None,
        surface: str | None = None,
    ) -> ContextSchemeSuggestForCategoriesResult:
        """Picker options for several categories in one round trip.

        Each category is answered as if its own assertions were not present,
        so a form can offer every alternative for a field that is already
        set. The result is a map from category id to that category's options,
        the same map :meth:`process` returns in ``suggestions_for`` when
        ``suggest_for`` names the categories.

        Args:
            assertions: The caller's full committed assertion set.
            category_ids: Categories to answer options for.
            output_format: Optional format the suggestion previews are
                rendered in: a format id, or for a scheme that declares
                surfaces a view id, a ``surface/view`` address, or the id of
                a form exactly one view names.
            surface: Optional suggestion surface, named with one of the
                scheme's scope ids. It restricts the options to the concepts
                and categories that surface owns.

        Raises:
            MalformedResponseError: The answer leaves out a category the
                request named, or is not the result the contract describes.
        """
        body: Dict[str, Any] = {
            "assertions": [_assertion_to_wire(item) for item in assertions],
            "categoryIds": category_ids,
        }
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        operation = self._ctx._describe("scheme/suggest-for-categories")

        def answers_every_category(decoded: Dict[str, Any], status: int) -> None:
            # A caller indexes the map by ids it already holds, so a missing
            # category would surface later as a KeyError far from the cause.
            # The model has already checked that the result is a map.
            result = decoded["result"]
            missing = [c for c in dict.fromkeys(category_ids) if c not in result]
            if missing:
                path = _json_path(("result", missing[0]))
                raise MalformedResponseError(
                    f"{operation} answered {status} with no result for: "
                    f"{', '.join(missing)}",
                    status,
                    path=path,
                )

        return self._post(
            "scheme/suggest-for-categories",
            body,
            ContextSchemeSuggestForCategoriesResult,
            check=answers_every_category,
        )

    def aggregate(
        self,
        markings: List[str],
        *,
        output_format: str | None = None,
        surface: str | None = None,
        input_format: str | None = None,
        context: Dict[str, Any] | None = None,
    ) -> ContextSchemeAggregateResult:
        """Aggregate multiple markings into a single rolled-up marking.

        Every member the aggregate result shares with a validate result means
        what it means there, ``valid`` and the ``notices`` collected for the
        rolled-up marking included.

        Args:
            markings: Rendered markings to combine.
            output_format: Optional output the rolled-up marking is written
                in: a format id, or for a scheme that declares surfaces a view
                id, a ``surface/view`` address, or the id of a form exactly
                one view names. It selects output only and never narrows what
                may be read. Omitted, the scheme's default format, or for a
                scheme that declares surfaces, each surface's default view
                for a whole marking, since a rollup is a whole.
            surface: Optional validation surface of the rollup, named with
                one of the scheme's scope ids. It names what the combined
                marking is, not what any one input was. Omitted, the rollup is
                evaluated as a whole marking.
            input_format: Optional format the input markings are written in.
                For a scheme that declares surfaces, a view id, a
                ``surface/view`` address, or the id of one of a view's forms.
                Omitted, recognition works it out.
            context: Optional processing context, forwarded verbatim to the
                engine. A role given here describes the markings the rollup
                reads; the rollup itself is a whole and is written as one.
        """
        body: Dict[str, Any] = {"inputs": markings}
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_value_if_set(body, "context", context)
        return self._post("scheme/aggregate", body, ContextSchemeAggregateResult)

    def aggregate_assertions(
        self,
        assertion_sets: List[List[Assertion]],
        *,
        output_format: str | None = None,
        surface: str | None = None,
        context: Dict[str, Any] | None = None,
    ) -> ContextSchemeAggregateResult:
        """Aggregate already-parsed assertion sets through the composed scheme.

        The assertion-set counterpart to :meth:`aggregate`: it takes one
        assertion array per marking, skips the string-parse stage, and runs the
        rest of the aggregate pipeline identically. Transports marking state
        losslessly: scope-only assertions and capture values that no rendered
        string can carry survive the round trip. Sends ``assertionSets`` on the
        wire (mutually exclusive with the ``inputs`` :meth:`aggregate` sends).

        Args:
            assertion_sets: One :class:`Assertion` array per marking to combine.
            output_format: Optional output the combined marking is written
                in: a format id, or for a scheme that declares surfaces a view
                id, a ``surface/view`` address, or the id of a form exactly
                one view names. Omitted, the scheme's default format, or for
                a scheme that declares surfaces, each surface's default view
                for a whole marking, since a rollup is a whole.
            surface: Optional validation surface of the rollup, named with
                one of the scheme's scope ids. Omitted, the marking is
                evaluated as a whole and every required category it owns must
                be covered; given a scope id, only the required categories
                that surface owns are demanded.
            context: Optional processing context, forwarded verbatim to the
                engine. A role given here describes the markings the rollup
                reads; the rollup itself is a whole and is written as one.

        Returns:
            A :class:`ContextSchemeAggregateResult` whose ``result`` field
            carries the aggregated marking, retaining every scoped and
            capture-value assertion even when the rendered string omits them,
            along with the notices collected for it.
        """
        body: Dict[str, Any] = {
            "assertionSets": [
                [_assertion_to_wire(a) for a in marking_set]
                for marking_set in assertion_sets
            ]
        }
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "surface", surface)
        _put_value_if_set(body, "context", context)
        return self._post("scheme/aggregate", body, ContextSchemeAggregateResult)

    def scan(
        self,
        text: str,
        *,
        output_format: str | None = None,
        input_format: str | None = None,
    ) -> ContextSchemeScanResult:
        """Scan free text for markings recognized by the context's scheme.

        Each match's ``result`` is what :meth:`validate` answers for that
        marking, read in the role it was found in. A scan reads documents and
        does not author them, so a match carries no fix paths; to correct one
        region, process that region. ``type`` is the output the match's
        ``rendered`` is written in when no ``output_format`` is named: for a
        scheme that declares surfaces, usually the ``surface/view`` address
        of the view it was read as, otherwise the default for its ``role``.

        Args:
            text: Free text to scan for markings.
            output_format: Optional output each match is rendered back in: a
                format id, or for a scheme that declares surfaces a view id,
                a ``surface/view`` address, or the id of a form exactly one
                view names. It selects output only and never narrows what
                may be read. Omitted, each match is written as its ``type``
                says.
            input_format: Optional format the markings in the text are written
                in. For a scheme that declares surfaces, a view id, a
                ``surface/view`` address, or the id of one of a view's forms.
                Omitted, recognition works it out.
        """
        body: Dict[str, Any] = {"text": text}
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        return self._post("scheme/scan", body, ContextSchemeScanResult)

    def render(
        self,
        assertions: List[Assertion],
        *,
        output_format: str | None = None,
        preservation: Literal["projection", "full"] | None = None,
    ) -> ContextSchemeRenderResult:
        """Render assertions into a marking, optionally requiring full fact preservation.

        Args:
            assertions: The facts to render.
            output_format: Optional format the assertions are rendered in: a
                format id, or for a scheme that declares surfaces a view id, a
                ``surface/view`` address, or the id of a form exactly one view
                names. Omitted, the scheme's default format.
            preservation: ``"projection"`` (the default) renders what the
                format writes and reports the rest on the result's
                ``assessment``. ``"full"`` fails rather than answering when a
                fact would be omitted, conflicting, or unrepresentable.
        """
        body: Dict[str, Any] = {
            "assertions": [_assertion_to_wire(a) for a in assertions]
        }
        _put_if_set(body, "outputFormat", output_format)
        _put_if_set(body, "preservation", preservation)
        return self._post("scheme/render", body, ContextSchemeRenderResult)

    def check_coverage(
        self,
        children: List[str],
        parent: str,
        *,
        output_format: str | None = None,
        input_format: str | None = None,
    ) -> ContextSchemeCoverageResult:
        """Report whether a set of child markings is covered by a parent marking.

        Args:
            children: Part markings to test.
            parent: Whole marking the parts are tested against.
            output_format: Optional output markings in the report are written
                in: a format id, or for a scheme that declares surfaces a view
                id, a ``surface/view`` address, or the id of a form exactly
                one view names. It selects output only and never narrows what
                may be read. Omitted, the scheme's default.
            input_format: Optional format the parent and part markings are
                written in. For a scheme that declares surfaces, a view id, a
                ``surface/view`` address, or the id of one of a view's forms.
                Omitted, recognition works it out.
        """
        body: Dict[str, Any] = {"children": children, "parent": parent}
        _put_if_set(body, "inputFormat", input_format)
        _put_if_set(body, "outputFormat", output_format)
        return self._post("scheme/check-coverage", body, ContextSchemeCoverageResult)

    def describe_concept(
        self, concept_id: str, category_id: str, view: Optional[str] = None
    ) -> ContextSchemeConceptDescriptionResult:
        """Describe a concept's definition, guidance, and applicable rules.

        Args:
            concept_id: Id of the concept to describe.
            category_id: Id of the category the concept belongs to.
            view: Optional view to name the concept in: a key of the concept's
                ``views``. Omitted, its default view.

        Returns:
            The concept's name, definition, guidance, the rules that involve
            it, and pre-formatted tooltip ``lines``.

        Raises:
            EzClassifyClientError: The server returned a non-2xx response (404
                naming the unknown concept or category) or the connection
                failed. A 429 carries ``retry_after``.
        """
        params: Dict[str, Any] = {"conceptId": concept_id, "categoryId": category_id}
        if view is not None:
            params["view"] = view
        return self._get(
            "scheme/describe-concept", ContextSchemeConceptDescriptionResult, params
        )

    def diff(
        self,
        marking_a: str,
        marking_b: str,
        *,
        input_format: str | None = None,
    ) -> ContextSchemeDiffResult:
        """Diff two marking strings into added / removed / common assertions.

        Args:
            marking_a: First marking.
            marking_b: Second marking.
            input_format: Optional format both markings are written in. For a
                scheme that declares surfaces, a view id, a ``surface/view``
                address, or the id of one of a view's forms. Omitted,
                recognition works it out. There is no output format: the
                result is assertions, not a rendered string.
        """
        body: Dict[str, Any] = {"a": marking_a, "b": marking_b}
        _put_if_set(body, "inputFormat", input_format)
        return self._post("scheme/diff", body, ContextSchemeDiffResult)

    def notices(self, assertions: List[Assertion]) -> ContextSchemeNoticesResult:
        """Collect the concept notices for a set of assertions.

        For assertions you are holding on their own. Anything that came back
        from :meth:`process`, :meth:`validate`, :meth:`aggregate`, or a result
        that carries one of those already has the same list on its ``notices``
        field, collected the same way, so reading notices for a marking you
        just processed does not need this call.
        """
        return self._post(
            "scheme/notices",
            {"assertions": [_assertion_to_wire(a) for a in assertions]},
            ContextSchemeNoticesResult,
        )

    def view(self) -> ContextSchemeViewResult:
        """Build a render-ready structural view of the context's composed scheme."""
        return self._post("scheme/view", {}, ContextSchemeViewResult)

    # ---- Scheme resources ---------------------------------------------------
    #
    # These read the composed scheme itself rather than operate on a marking,
    # and they answer with the bare resource: no ``result``/``resolution``
    # envelope, because there is no operation whose provenance would go in one.
    # ``apply_preset`` below is the exception, and it is enveloped precisely
    # because it IS an operation: it expands a preset and validates the
    # marking it stands for, so it answers with the same
    # ContextSchemeValidateResult as ``validate``.
    #
    # Like every operation above, these read the scheme this view is bound
    # to: the primary for ``ctx.scheme``, the selected one for a view from
    # ``ctx.schemes.get``. A crosswalk's source and target schemes are held by
    # the same Context and read that way.
    #
    # The bodies are typed by the generated models, not by shapes declared
    # here.

    def summary(self) -> SchemeSummary:
        """Read the composed scheme's summary metadata.

        Identity, presentation configuration, default render format, and scope
        label for the context's composed scheme (base plus its declared
        layers). There is no ``layers`` parameter: the layers belong to the
        context.

        Returns:
            The summary as a :class:`SchemeSummary`.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get("scheme", SchemeSummary)

    def concepts(self) -> List[ConceptView]:
        """List every concept of the composed scheme.

        Returns:
            One :class:`ConceptView` per concept, the shape a local engine's
            scheme view carries.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get_list("scheme/concepts", ConceptView)

    def categories(self) -> List[CategoryView]:
        """List every category of the composed scheme, in declared order.

        Returns:
            One :class:`CategoryView` per category, the shape a local engine's
            scheme view carries.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get_list("scheme/categories", CategoryView)

    def formats(self) -> List[FormatView]:
        """List the formats the composed scheme writes.

        Returns:
            One :class:`FormatView` per format: its id, the surface it writes,
            its resolved layout, and how its text is framed. The field trees
            stay server-side.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get_list("scheme/formats", FormatView)

    def scopes(self) -> List[SchemeScope]:
        """List the composed scheme's scope definitions, in declaration order.

        Returns:
            One :class:`SchemeScope` per declared scope, in the order a
            selector should offer them. Empty when the scheme declares none.
            Which scope is the default is the summary's ``default_scope``; no
            entry here marks it.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get_list("scheme/scopes", SchemeScope)

    def label_presets(self) -> List[LabelPresetView]:
        """List the label presets of this view's scheme.

        Name and scope only: each preset's marking string and tag list stay
        server-side, so :meth:`apply_preset` on the same view is the only way
        to expand one.

        Returns:
            One :class:`LabelPresetView` per preset; empty when the scheme
            declares none.

        Raises:
            MalformedResponseError: The answer is not the one the contract
                describes.
            EzClassifyClientError: The server returned a non-2xx response or
                the connection failed. A 429 carries ``retry_after``.
        """
        return self._get_list("scheme/label-presets", LabelPresetView)

    def apply_preset(
        self, preset_id: str, *, output_format: str | None = None
    ) -> ContextSchemeValidateResult:
        """Expand a label preset and return what validate answers for it.

        The only enveloped call in this group: expanding a preset runs the
        marking through the composed scheme, so it answers with the standard
        context operation envelope, exactly as :meth:`validate` does. A preset
        is a stored marking, so there is nothing to correct and no fix path
        to offer: the answer is the facts, the verdicts, the rendering and its
        assessment, the notices and the display color.

        Args:
            preset_id: Id of the preset to expand, from :meth:`label_presets`.
            output_format: Optional output the marking is rendered in: a
                format id, or for a scheme that declares surfaces a view id,
                a ``surface/view`` address, or the id of a form exactly one
                view names. The scheme default is used when omitted.

        Returns:
            The expanded marking in the context operation envelope.

        Raises:
            ValueError: ``preset_id`` was blank.
            EzClassifyClientError: The server returned a non-2xx response
                (404 when the scheme declares no preset by that id, 400 for an
                ``output_format`` the scheme does not declare) or the
                connection failed. A 429 carries ``retry_after``.
        """
        if not preset_id or not preset_id.strip():
            raise ValueError("preset_id must not be blank or empty")
        body: Dict[str, Any] = {"presetId": preset_id}
        _put_if_set(body, "outputFormat", output_format)
        return self._post("scheme/apply-preset", body, ContextSchemeValidateResult)


class CtxSchemes:
    """The schemes a :class:`EzClassifyContext` holds, reached by key.

    A Context can hold more than its primary scheme: a crosswalk's source and
    target, or an additional scheme. ``ctx.schemes.get(key)`` returns the view
    of one of them; ``ctx.scheme`` stays the primary view.
    """

    def __init__(self, ctx: EzClassifyContext) -> None:
        self._ctx = ctx
        self._views: Dict[str, CtxScheme] = {}

    def get(self, key: str) -> CtxScheme:
        """Return the view of one scheme this Context holds.

        The view answers every operation and read ``ctx.scheme`` does, against
        the scheme ``key`` names, and sends ``key`` as ``?scheme=`` on each
        request.

        Views are kept per key, so asking twice for the same key returns the
        same view. Their answers share the handle's response cache, keyed by
        scheme, so one scheme's answer is never served for another's.

        The server decides what a key names, not this client: a key the
        Context does not hold answers 404 ``scheme_not_found`` on the first
        request the view makes, and the call raises. Nothing falls back to the
        primary.

        Args:
            key: Context-local key of the scheme, as
                ``describe().schemes[i].selector`` reports it.

        Returns:
            The scheme view bound to ``key``.

        Raises:
            ValueError: ``key`` is blank. An empty key would reach the server
                as ``?scheme=`` and could never name a scheme.
        """
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-blank string")
        view = self._views.get(key)
        if view is None:
            view = self._views.setdefault(key, CtxScheme(self._ctx, key))
        return view


class CtxGuide:
    """Guide-domain operations bound to a :class:`EzClassifyContext`."""

    def __init__(self, ctx: EzClassifyContext) -> None:
        self._ctx = ctx

    def scan(self, text: str, guide_id: Optional[str] = None) -> ContextGuideScanResult:
        """Scan free text for guide rule matches, optionally narrowed to one guide."""
        body: Dict[str, Any] = {"text": text}
        if guide_id is not None:
            body["guideId"] = guide_id
        return self._ctx._post("guide/scan", body, ContextGuideScanResult)

    def evaluate(self, guide_id: str, *rule_ids: str) -> ContextGuideEvaluationResult:
        """Evaluate a guide with the given rule selection."""
        return self._ctx._post(
            "guide/evaluate",
            {"guideId": guide_id, "selectedRuleIds": list(rule_ids)},
            ContextGuideEvaluationResult,
        )

    def evaluate_many(
        self, *selections: GuideRuleSelection
    ) -> ContextGuideEvaluationResult:
        """Roll up rules selected from several guides.

        Each selection names the guide that holds its rule, so two guides
        that use the same rule id hold two rules. Each guide evaluates the
        rules selected from it, with its own dependencies and overrides, and
        the outcomes are rolled up per target scheme.

        Raises:
            ValueError: A selection's ``guide_id`` or ``rule_id`` was blank.
        """
        wire: List[Dict[str, str]] = []
        for selection in selections:
            if not selection.guide_id or not selection.guide_id.strip():
                raise ValueError("guide_id must not be blank or empty")
            if not selection.rule_id or not selection.rule_id.strip():
                raise ValueError("rule_id must not be blank or empty")
            wire.append({"guideId": selection.guide_id, "ruleId": selection.rule_id})
        return self._ctx._post(
            "guide/evaluate", {"selections": wire}, ContextGuideEvaluationResult
        )

    def view(self, guide_id: Optional[str] = None) -> ContextGuideViewResult:
        """Build a render-ready structural view of a guide (defaults to the first)."""
        body: Dict[str, Any] = {}
        if guide_id is not None:
            body["guideId"] = guide_id
        return self._ctx._post("guide/view", body, ContextGuideViewResult)


class CtxAccess:
    """Access-control operations bound to a :class:`EzClassifyContext`."""

    def __init__(self, ctx: EzClassifyContext) -> None:
        self._ctx = ctx

    def check(
        self,
        data_assertions: List[Assertion],
        user_attributes: Dict[str, Any],
        *,
        context: Dict[str, Any] | None = None,
    ) -> ContextAccessDecisionResult:
        """Check whether a subject's user attributes satisfy the context's access policy.

        Args:
            data_assertions: The target's assertions.
            user_attributes: The subject's attributes, interpreted by the
                access policy.
            context: Optional comparison data the marking does not carry,
                such as distribution organizations. When decision audit is
                enabled, the deployment names the user and resource ids it
                requires in here.
        """
        body: Dict[str, Any] = {
            "assertions": [_assertion_to_wire(a) for a in data_assertions],
            "userAttributes": user_attributes,
        }
        _put_value_if_set(body, "context", context)
        return self._ctx._post("access/check", body, ContextAccessDecisionResult)

    def check_by_marking(
        self,
        marking: str,
        user_attributes: Dict[str, Any],
        *,
        context: Dict[str, Any] | None = None,
    ) -> ContextAccessDecisionResult:
        """Check access from a marking string; the server extracts data assertions.

        Args:
            marking: The target marking, parsed through the bound scheme.
            user_attributes: The subject's attributes, interpreted by the
                access policy.
            context: Optional comparison data the marking does not carry; see
                :meth:`check`.
        """
        body: Dict[str, Any] = {"marking": marking, "userAttributes": user_attributes}
        _put_value_if_set(body, "context", context)
        return self._ctx._post("access/check", body, ContextAccessDecisionResult)

    def describe_requirements(
        self, marking: str, *, assertions: List[Assertion] | None = None
    ) -> ContextAccessRequirementsResult:
        """Summarize the aggregated access requirements for a marking.

        Args:
            marking: Marking parsed through the bound scheme.
            assertions: Optional structured assertions merged with the ones
                parsed from ``marking``.
        """
        body: Dict[str, Any] = {"marking": marking}
        _put_assertions_if_set(body, assertions)
        return self._ctx._post(
            "access/describe-requirements", body, ContextAccessRequirementsResult
        )

    def rules(self) -> CtxAccessRulesResponseBody:
        """Describe every access rule declared by the bound Context."""
        return self._ctx._get("access/rules", CtxAccessRulesResponseBody)


class CtxCrosswalk:
    """Directional crosswalk operations bound to a Context."""

    def __init__(self, ctx: EzClassifyContext) -> None:
        self._ctx = ctx

    def describe(self) -> CtxCrosswalkDescribeResponseBody:
        """Describe every crosswalk the bound Context holds, in declaration order.

        Each crosswalk names its source and target by the scheme selectors
        :meth:`EzClassifyContext.describe` lists under ``schemes``, and carries
        the mappings and selections a translation applies. ``crosswalks`` is
        empty when the Context declares none. The answer goes through the
        response cache like :meth:`CtxAccess.rules`.
        """
        return self._ctx._get("crosswalk/describe", CtxCrosswalkDescribeResponseBody)

    # One overload per source spelling, as on CtxScheme.validate.
    @overload
    def translate(
        self, crosswalk_id: str, *, marking: str
    ) -> ContextCrosswalkTranslationResult: ...

    @overload
    def translate(
        self, crosswalk_id: str, *, assertions: List[Assertion]
    ) -> ContextCrosswalkTranslationResult: ...

    def translate(
        self,
        crosswalk_id: str,
        *,
        marking: str | None = None,
        assertions: List[Assertion] | None = None,
    ) -> ContextCrosswalkTranslationResult:
        """Translate exactly one rendered or structured source through a crosswalk.

        Raises:
            ValueError: ``crosswalk_id`` was blank, or neither or both of
                ``marking`` and ``assertions`` were given.
        """
        if not crosswalk_id or not crosswalk_id.strip():
            raise ValueError("crosswalk_id must not be blank or empty")
        if (marking is None) == (assertions is None):
            raise ValueError("provide exactly one of marking or assertions")
        body: Dict[str, Any] = {"crosswalkId": crosswalk_id}
        if marking is not None:
            body["marking"] = marking
        else:
            body["assertions"] = [_assertion_to_wire(item) for item in assertions or []]
        return self._ctx._post(
            "crosswalk/translate", body, ContextCrosswalkTranslationResult
        )


class CtxDocument:
    """Document-level operations bound to a :class:`EzClassifyContext`."""

    def __init__(self, ctx: EzClassifyContext) -> None:
        self._ctx = ctx

    def audit(
        self,
        text: str,
        *,
        guide_determinations: GuideDeterminationInput | Dict[str, Any] | None = None,
        response_profile: Literal["summary", "standard", "full"] | None = None,
    ) -> ContextDocumentAuditResult:
        """Audit a document and return its resolved Context envelope.

        Args:
            text: Exact Unicode document text sent to the server.
            guide_determinations: Optional accepted/rejected findings and manual selections.
            response_profile: Optional ``summary``, ``standard``, or ``full`` projection.

        Returns:
            The typed audit envelope, including resolution, provenance, limitations,
            and projection metadata.
        """
        body: Dict[str, Any] = {"text": text}
        if guide_determinations is not None:
            body["guideDeterminations"] = (
                guide_determinations.model_dump(by_alias=True, exclude_none=True)
                if isinstance(guide_determinations, GuideDeterminationInput)
                else guide_determinations
            )
        if response_profile is not None:
            body["responseProfile"] = response_profile
        return self._ctx._post("document/audit", body, ContextDocumentAuditResult)
