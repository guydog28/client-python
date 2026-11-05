"""Request-shape gate.

Every client call that sends a body is driven through the real client with
every optional argument supplied, and the body it puts on the wire is validated
against that operation's request schema in the vendored contract
(``vendor/spec/openapi.yaml``). The request schemas close their objects
(``additionalProperties: false``), so a field the contract renamed or removed
fails here instead of as a 400 from a live server.

Requests are closed in the query too: the server answers 400 to a query
parameter the operation does not declare. Every call is therefore also checked
for the query it sends, which must be exactly what the operation declares once
every optional argument is supplied, and nothing at all for a POST.

This exists because the failure it catches is invisible to the rest of the
suite: when a request field is renamed in the contract, a method that keeps
sending the former name still passes a test that asserts that same name.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

import httpx
import pytest
import respx
import yaml

from ezclassify_rest_client import EzClassifyClient, EzClassifyContext
from ezclassify_contract import (
    Assertion,
    GuideDeterminationInput,
    GuideFindingDetermination,
)

SPEC_PATH = Path(__file__).resolve().parents[2] / "vendor/spec/openapi.yaml"

_BASE = "http://conformance.invalid"
_CTX = "acme-marking"
_VER = "1.0.0"
_ROUTE_PREFIX = "/v1/ctx/{ctxId}/{version}/"
_CTX_PREFIX = f"/v1/ctx/{_CTX}/{_VER}/"

_ANNOTATIONS = frozenset(
    {
        "description",
        "title",
        "default",
        "example",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "$comment",
    }
)


class _Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with the YAML 1.2 core-schema reading of plain scalars.

    PyYAML resolves YAML 1.1, where ``yes``, ``on`` and bare dates turn into
    booleans and datetimes. JSON Schema compares values as JSON, so an enum or
    const read that way would compare as the wrong type. Only ``true`` and
    ``false`` are booleans here, and dates stay strings.
    """


_Yaml12Loader.yaml_implicit_resolvers = {
    first: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)


class OpenApiRequestSchemas:
    """The request schemas of the vendored OpenAPI document, and a validator.

    The validator covers the JSON Schema subset those schemas use and fails
    closed: a schema keyword it does not implement raises rather than being
    skipped, so a contract that starts using one forces this harness to learn
    it instead of silently passing everything that keyword would have
    rejected.
    """

    def __init__(self, document: Dict[str, Any]) -> None:
        self._components: Dict[str, Any] = document["components"]["schemas"]
        self._closed = False
        self.request_schemas: Dict[Tuple[str, str], Any] = {}
        self._query: Dict[Tuple[str, str], Set[str]] = {}
        for path, item in document["paths"].items():
            for method, operation in item.items():
                if not isinstance(operation, dict):
                    continue
                self._query[(method, path)] = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "query"
                }
                schema = (
                    operation.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if schema is not None:
                    self.request_schemas[(method, path)] = schema
        assert self.request_schemas, (
            "read no request schemas out of vendor/spec/openapi.yaml"
        )

    @classmethod
    def load(cls) -> "OpenApiRequestSchemas":
        text = SPEC_PATH.read_text(encoding="utf-8")
        return cls(yaml.load(text, Loader=_Yaml12Loader))  # noqa: S506

    def validate(self, method: str, path: str, body: Any) -> List[str]:
        """Validate a request body; one message per violation, empty when valid."""
        schema = self.request_schemas.get((method, path))
        assert schema is not None, (
            f"the contract declares no request body for {method.upper()} {path}"
        )
        errors: List[str] = []
        self._check(body, schema, "$", errors)
        return errors

    def validate_closed(self, component: str, value: Any) -> List[str]:
        """Validate a value against a schema component with every object closed.

        Response schemas leave their objects open so a server can add a
        member without breaking a client. A hand-written response fixture
        must not lean on that: a member the contract dropped would still
        pass. Here an object schema that lists its properties refuses any
        other, wherever the contract did not say what to do with them.

        Raises:
            KeyError: The contract has no component by that name.
        """
        self._closed = True
        try:
            errors: List[str] = []
            self._check(
                value, self._resolve(f"#/components/schemas/{component}"), "$", errors
            )
            return errors
        finally:
            self._closed = False

    def declared_query(self, method: str, path: str) -> Set[str]:
        """Query parameter names an operation declares; empty when it has none."""
        return self._query[(method, path)]

    def declared_properties(self, method: str, path: str) -> Set[str]:
        """Top-level property names an operation's request schema declares.

        Follows ``$ref`` and the ``anyOf`` and ``if``/``then``/``else``
        branches, so a field declared on any branch counts.
        """
        names: Set[str] = set()
        pending = [self.request_schemas[(method, path)]]
        while pending:
            schema = pending.pop()
            if isinstance(schema, bool):
                continue
            if "$ref" in schema:
                pending.append(self._resolve(schema["$ref"]))
            names.update(schema.get("properties") or {})
            pending.extend(schema.get("anyOf") or [])
            pending.extend(schema[key] for key in ("then", "else") if key in schema)
        return names

    def _check(self, value: Any, schema: Any, at: str, errors: List[str]) -> None:
        if isinstance(schema, bool):
            if not schema:
                errors.append(f"{at}: no value is allowed here")
            return

        # Only a schema that says it is an object is closed. A condition such
        # as an `if` lists the one property it tests; closed, it would be
        # false for every object with any other property, and its `then`
        # would silently stop applying.
        if (
            self._closed
            and schema.get("type") == "object"
            and "properties" in schema
            and "additionalProperties" not in schema
        ):
            schema = {**schema, "additionalProperties": False}
        for keyword, argument in schema.items():
            if keyword == "$ref":
                self._check(value, self._resolve(argument), at, errors)
            elif keyword == "type":
                accepted = argument if isinstance(argument, list) else [argument]
                if not any(_is_type(value, t) for t in accepted):
                    errors.append(
                        f"{at}: {_show(value)} is not of type {' | '.join(accepted)}"
                    )
            elif keyword == "enum":
                if not any(_json_equal(option, value) for option in argument):
                    errors.append(
                        f"{at}: {_show(value)} is not one of {_show(argument)}"
                    )
            elif keyword == "const":
                if not _json_equal(argument, value):
                    errors.append(f"{at}: {_show(value)} is not {_show(argument)}")
            elif keyword == "required":
                if isinstance(value, dict):
                    for name in argument:
                        if name not in value:
                            errors.append(
                                f"{at}: required property '{name}' is missing"
                            )
            elif keyword == "properties":
                if isinstance(value, dict):
                    for name, property_schema in argument.items():
                        if name in value:
                            self._check(
                                value[name], property_schema, f"{at}.{name}", errors
                            )
            elif keyword == "additionalProperties":
                if isinstance(value, dict):
                    declared = schema.get("properties") or {}
                    for name, item in value.items():
                        if name in declared:
                            continue
                        if isinstance(argument, bool):
                            if not argument:
                                errors.append(
                                    f"{at}: property '{name}' is not allowed by the contract"
                                )
                        else:
                            self._check(item, argument, f"{at}.{name}", errors)
            elif keyword == "items":
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        self._check(item, argument, f"{at}[{index}]", errors)
            elif keyword == "minItems":
                if isinstance(value, list) and len(value) < argument:
                    errors.append(
                        f"{at}: {len(value)} items, the contract needs at least {argument}"
                    )
            elif keyword == "pattern":
                if isinstance(value, str) and re.search(argument, value) is None:
                    errors.append(f"{at}: {_show(value)} does not match {argument!r}")
            elif keyword == "not":
                if self._passes(value, argument, at):
                    errors.append(f"{at}: {_show(value)} matches a schema it must not")
            elif keyword == "anyOf":
                if not any(self._passes(value, branch, at) for branch in argument):
                    errors.append(
                        f"{at}: {_show(value)} matches none of the anyOf branches"
                    )
            elif keyword == "if":
                branch = (
                    schema.get("then")
                    if self._passes(value, argument, at)
                    else schema.get("else")
                )
                if branch is not None:
                    self._check(value, branch, at, errors)
            elif keyword in ("then", "else"):
                continue  # applied by "if"
            elif keyword not in _ANNOTATIONS:
                raise NotImplementedError(
                    f"the request-schema validator does not implement {keyword!r} "
                    f"(at {at}). Teach OpenApiRequestSchemas._check the keyword "
                    "rather than ignoring it."
                )

    def _passes(self, value: Any, schema: Any, at: str) -> bool:
        scratch: List[str] = []
        self._check(value, schema, at, scratch)
        return not scratch

    def _resolve(self, reference: str) -> Any:
        prefix = "#/components/schemas/"
        if not reference.startswith(prefix):
            raise NotImplementedError(f"unsupported $ref {reference!r}")
        name = reference[len(prefix) :]
        if name not in self._components:
            raise KeyError(f"unresolved $ref {reference!r}")
        return self._components[name]


def _is_type(value: Any, json_type: str) -> bool:
    # bool is a subclass of int in Python; JSON keeps them apart.
    if json_type == "null":
        return value is None
    if json_type == "object":
        return isinstance(value, dict)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "integer":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and float(value).is_integer()
        )
    raise NotImplementedError(f"unknown JSON Schema type {json_type!r}")


def _json_equal(a: Any, b: Any) -> bool:
    """Compare as JSON values: ``True`` is not ``1`` and ``1`` equals ``1.0``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _show(value: Any) -> str:
    return json.dumps(value)


@pytest.fixture(scope="module")
def spec() -> OpenApiRequestSchemas:
    return OpenApiRequestSchemas.load()


_LEVEL = Assertion(
    categoryId="level",
    conceptId="HIGH",
    confidence="certain",
    source="parse",
    value="H",
)

_DETERMINATIONS = GuideDeterminationInput(
    findings=[
        GuideFindingDetermination(
            findingId="finding-1",
            documentDigest="sha256:abc",
            decision="accepted",
            reason="Confirmed by analyst",
        )
    ],
    manualSelections=[],
)

_PART_OF = {"role": "part", "partOf": {"rendered": "H//A"}}

# One case per client call that sends a body, keyed by a readable name. Each
# supplies every optional argument the call takes, so the whole option surface
# reaches the wire. Calls that build a different body for the same route get
# their own case.
CASES: Dict[str, Tuple[str, Callable[[EzClassifyContext], Any]]] = {
    "scheme.process": (
        "scheme/process",
        lambda c: c.scheme.process(
            "H//A",
            output_format="banner",
            surface="portion",
            input_format="portion",
            assertions=[_LEVEL],
            context=_PART_OF,
            parts=["A"],
            outputs=["marking/banner", "marking/portion"],
            suggest_for=["level"],
        ),
    ),
    # validate carries the marking as text or as facts, never both, so each
    # spelling is its own case.
    "scheme.validate-text": (
        "scheme/validate",
        lambda c: c.scheme.validate(
            "H//A",
            output_format="banner",
            surface="portion",
            input_format="portion",
            context=_PART_OF,
            parts=["A"],
        ),
    ),
    "scheme.validate-facts": (
        "scheme/validate",
        lambda c: c.scheme.validate(
            assertions=[_LEVEL],
            output_format="banner",
            surface="portion",
            context=_PART_OF,
            parts=["A"],
        ),
    ),
    "scheme.explain": (
        "scheme/explain",
        lambda c: c.scheme.explain(
            "H//A",
            output_format="banner",
            surface="portion",
            input_format="portion",
            assertions=[_LEVEL],
            context=_PART_OF,
            parts=["A"],
        ),
    ),
    "scheme.suggest": (
        "scheme/suggest",
        lambda c: c.scheme.suggest(
            "H//",
            output_format="banner",
            surface="portion",
            input_format="portion",
            filter="hi",
            include_gated=True,
        ),
    ),
    "scheme.suggest-facts": (
        "scheme/suggest",
        lambda c: c.scheme.suggest(
            assertions=[_LEVEL],
            output_format="banner",
            surface="portion",
            filter="hi",
            include_gated=True,
        ),
    ),
    "scheme.suggest-for-categories": (
        "scheme/suggest-for-categories",
        lambda c: c.scheme.suggest_for_categories(
            [_LEVEL], ["level", "audience"], output_format="banner", surface="portion"
        ),
    ),
    "scheme.aggregate": (
        "scheme/aggregate",
        lambda c: c.scheme.aggregate(
            ["H", "L"],
            output_format="banner",
            surface="portion",
            input_format="portion",
            context=_PART_OF,
        ),
    ),
    "scheme.aggregate-assertions": (
        "scheme/aggregate",
        lambda c: c.scheme.aggregate_assertions(
            [[_LEVEL]], output_format="banner", surface="portion", context=_PART_OF
        ),
    ),
    "scheme.scan": (
        "scheme/scan",
        lambda c: c.scheme.scan(
            "text H text",
            output_format="banner",
            input_format="portion",
        ),
    ),
    "scheme.render": (
        "scheme/render",
        lambda c: c.scheme.render(
            [_LEVEL], output_format="banner", preservation="full"
        ),
    ),
    "scheme.normalize": (
        "scheme/normalize",
        lambda c: c.scheme.normalize(
            "h", output_format="banner", input_format="portion"
        ),
    ),
    "scheme.check-coverage": (
        "scheme/check-coverage",
        lambda c: c.scheme.check_coverage(
            ["L"], "H", output_format="banner", input_format="portion"
        ),
    ),
    "scheme.diff": (
        "scheme/diff",
        lambda c: c.scheme.diff("H", "L", input_format="portion"),
    ),
    "scheme.filter-concepts": (
        "scheme/filter-concepts",
        lambda c: c.scheme.filter_concepts("hi"),
    ),
    "scheme.notices": ("scheme/notices", lambda c: c.scheme.notices([_LEVEL])),
    "scheme.view": ("scheme/view", lambda c: c.scheme.view()),
    "scheme.apply-preset": (
        "scheme/apply-preset",
        lambda c: c.scheme.apply_preset("default-label", output_format="banner"),
    ),
    "guide.scan": ("guide/scan", lambda c: c.guide.scan("secret text", guide_id="g1")),
    "guide.evaluate": ("guide/evaluate", lambda c: c.guide.evaluate("g1", "r1")),
    "guide.evaluate_many": ("guide/evaluate", lambda c: c.guide.evaluate_many("r1")),
    "guide.filter-rules": (
        "guide/filter-rules",
        lambda c: c.guide.filter_rules("sec", guide_id="g1"),
    ),
    "guide.describe-rule": (
        "guide/describe-rule",
        lambda c: c.guide.describe_rule("r1", guide_id="g1"),
    ),
    "guide.view": ("guide/view", lambda c: c.guide.view(guide_id="g1")),
    "access.check": (
        "access/check",
        lambda c: c.access.check(
            [_LEVEL], {"clearance": "high"}, context={"orgs": ["org-1"]}
        ),
    ),
    "access.check-by-marking": (
        "access/check",
        lambda c: c.access.check_by_marking(
            "H", {"clearance": "high"}, context={"orgs": ["org-1"]}
        ),
    ),
    "access.describe-requirements": (
        "access/describe-requirements",
        lambda c: c.access.describe_requirements("H", assertions=[_LEVEL]),
    ),
    "access.describe-rule": (
        "access/describe-rule",
        lambda c: c.access.describe_rule("rule-1"),
    ),
    "crosswalk.translate-marking": (
        "crosswalk/translate",
        lambda c: c.crosswalk.translate("cw-1", marking="H"),
    ),
    "crosswalk.translate-assertions": (
        "crosswalk/translate",
        lambda c: c.crosswalk.translate("cw-1", assertions=[_LEVEL]),
    ),
    "document.audit": (
        "document/audit",
        lambda c: c.document.audit(
            "document text",
            guide_determinations=_DETERMINATIONS,
            response_profile="full",
        ),
    ),
}


def _send(case_name: str) -> httpx.Request:
    """Drive one case through the real client and return the request it sent."""
    _, invoke = CASES[case_name]
    with respx.mock(base_url=_BASE, assert_all_called=False) as router:
        # The stub answers every operation with an empty object, which most
        # result models reject. Only the request matters here, and the
        # assertions below prove exactly one was sent.
        catch_all = router.route().mock(return_value=httpx.Response(200, json={}))
        with EzClassifyContext(_BASE, context_id=_CTX, context_version=_VER) as ctx:
            try:
                invoke(ctx)
            except Exception:  # noqa: BLE001, S110
                pass

    assert catch_all.call_count == 1, (
        f"{case_name} sent {catch_all.call_count} requests; expected exactly one"
    )
    return catch_all.calls.last.request


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_request_body_validates_against_the_contract_request_schema(
    spec: OpenApiRequestSchemas, case_name: str
) -> None:
    route, _ = CASES[case_name]
    request = _send(case_name)
    assert request.method == "POST"
    assert request.url.path == _CTX_PREFIX + route, (
        f"{case_name} posted to {request.url.path}, not {_CTX_PREFIX + route}"
    )

    body = json.loads(request.content)
    errors = spec.validate("post", _ROUTE_PREFIX + route, body)
    assert not errors, "\n  ".join(
        [f"{case_name} sent a body the contract rejects:", json.dumps(body), *errors]
    )


def test_every_contract_request_body_has_a_case(spec: OpenApiRequestSchemas) -> None:
    """A new operation with a body cannot ship without its body being checked."""
    covered = {_ROUTE_PREFIX + route for route, _ in CASES.values()}
    missing = sorted(
        f"POST {path}"
        for (method, path) in spec.request_schemas
        if method == "post" and path not in covered
    )
    non_post = sorted(
        f"{method.upper()} {path}"
        for (method, path) in spec.request_schemas
        if method != "post"
    )

    assert not missing, "no request-schema case for: " + ", ".join(missing)
    assert not non_post, (
        "the contract now has request bodies on non-POST operations; extend the "
        "cases to cover them: " + ", ".join(non_post)
    )


def test_every_contract_request_property_reaches_the_wire(
    spec: OpenApiRequestSchemas,
) -> None:
    """Every field a request schema declares is sent by at least one case.

    Each case supplies every optional argument its call takes, so a declared
    field no case sends is a field the client has no argument for. Without
    this, the contract can add an option and the client can ship without a
    way to set it while every body it does send still validates.
    """
    sent: Dict[str, Set[str]] = {}
    for case_name, (route, _) in CASES.items():
        body = json.loads(_send(case_name).content)
        sent.setdefault(route, set()).update(body)

    unsent = {
        route: sorted(spec.declared_properties("post", _ROUTE_PREFIX + route) - keys)
        for route, keys in sent.items()
    }
    unsent = {route: fields for route, fields in unsent.items() if fields}
    assert not unsent, "the client never sends these contract fields: " + "; ".join(
        f"{route}: {', '.join(fields)}" for route, fields in sorted(unsent.items())
    )


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_a_post_sends_no_query_because_the_contract_declares_none(
    spec: OpenApiRequestSchemas, case_name: str
) -> None:
    route, _ = CASES[case_name]
    request = _send(case_name)
    assert spec.declared_query("post", _ROUTE_PREFIX + route) == set()
    assert request.url.query == b"", (
        f"{case_name} sent query {request.url.query!r}; the server refuses it"
    )


class _Harness:
    """The two client objects a read can go through, over one stubbed server."""

    def __init__(self, client: EzClassifyClient, ctx: EzClassifyContext) -> None:
        self.client = client
        self.ctx = ctx


# One case per client call that reads with GET, keyed by the contract's path
# template. Each supplies every optional argument, so the whole query surface
# reaches the wire.
QUERY_CASES: Dict[str, Tuple[str, Callable[[_Harness], Any]]] = {
    "deployment.health": ("/v1/health", lambda h: h.client.ping()),
    "deployment.list-contexts": ("/v1/ctx", lambda h: h.client.list_contexts()),
    "deployment.list-versions": (
        "/v1/ctx/{ctxId}",
        lambda h: h.client.list_context_versions(_CTX),
    ),
    "context.describe": ("/v1/ctx/{ctxId}/{version}", lambda h: h.ctx.resolve()),
    "scheme.summary": (
        _ROUTE_PREFIX + "scheme",
        lambda h: h.ctx.scheme.summary(scheme="acme"),
    ),
    "scheme.concepts": (
        _ROUTE_PREFIX + "scheme/concepts",
        lambda h: h.ctx.scheme.concepts(scheme="acme"),
    ),
    "scheme.categories": (
        _ROUTE_PREFIX + "scheme/categories",
        lambda h: h.ctx.scheme.categories(scheme="acme"),
    ),
    "scheme.formats": (
        _ROUTE_PREFIX + "scheme/formats",
        lambda h: h.ctx.scheme.formats(scheme="acme"),
    ),
    "scheme.grammar": (
        _ROUTE_PREFIX + "scheme/grammar",
        lambda h: h.ctx.scheme.grammar(scheme="acme"),
    ),
    "scheme.scopes": (
        _ROUTE_PREFIX + "scheme/scopes",
        lambda h: h.ctx.scheme.scopes(scheme="acme"),
    ),
    "scheme.label-presets": (
        _ROUTE_PREFIX + "scheme/label-presets",
        lambda h: h.ctx.scheme.label_presets(),
    ),
    "scheme.describe-concept": (
        _ROUTE_PREFIX + "scheme/describe-concept",
        lambda h: h.ctx.scheme.describe_concept("HIGH", "level", view="default"),
    ),
    "access.rules": (_ROUTE_PREFIX + "access/rules", lambda h: h.ctx.access.rules()),
}


def _send_read(case_name: str) -> httpx.Request:
    """Drive one read through the real client and return the request it sent."""
    _, invoke = QUERY_CASES[case_name]
    with respx.mock(base_url=_BASE, assert_all_called=False) as router:
        catch_all = router.route().mock(return_value=httpx.Response(200, json={}))
        with (
            EzClassifyClient(_BASE) as client,
            EzClassifyContext(_BASE, context_id=_CTX, context_version=_VER) as ctx,
        ):
            try:
                invoke(_Harness(client, ctx))
            except Exception:  # noqa: BLE001, S110
                pass

    assert catch_all.call_count == 1, (
        f"{case_name} sent {catch_all.call_count} requests; expected exactly one"
    )
    return catch_all.calls.last.request


@pytest.mark.parametrize("case_name", sorted(QUERY_CASES))
def test_a_read_sends_exactly_the_query_the_contract_declares(
    spec: OpenApiRequestSchemas, case_name: str
) -> None:
    template, _ = QUERY_CASES[case_name]
    request = _send_read(case_name)
    assert request.method == "GET"
    assert request.url.path == template.replace("{ctxId}", _CTX).replace(
        "{version}", _VER
    )

    declared = spec.declared_query("get", template)
    sent = set(request.url.params)
    assert sent == declared, (
        f"{case_name} sent query {sorted(sent)}; the contract declares "
        f"{sorted(declared)} and refuses anything else with a 400"
    )


# The one read the client never sends; the root suite's
# test_spec_operation_coverage keeps the reason.
_UNSENT_READS = {"/v1/ready"}


def test_every_read_the_contract_declares_has_a_query_case() -> None:
    """A new GET operation cannot ship without its query being checked."""
    covered = {template for template, _ in QUERY_CASES.values()}
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    reads = sorted(path for path, item in document["paths"].items() if "get" in item)
    assert [p for p in reads if p not in covered | _UNSENT_READS] == []
    assert _UNSENT_READS <= set(reads)


# Negative controls. A gate that cannot fail proves nothing, so pin the two
# failure modes it exists for: a removed field, and a missing required one.


@pytest.mark.parametrize(
    ("route", "body", "field"),
    [
        ("scheme/process", {"input": "H", "format": "banner"}, "format"),
        ("scheme/process", {"input": "H", "scope": "portion"}, "scope"),
        ("scheme/validate", {"input": "H", "scope": "portion"}, "scope"),
        ("scheme/process", {"input": "H", "tolerant": True}, "tolerant"),
        ("scheme/process", {"input": "H", "normalization": "loose"}, "normalization"),
        ("scheme/explain", {"input": "H", "outputs": ["banner"]}, "outputs"),
        ("scheme/explain", {"input": "H", "suggestFor": ["level"]}, "suggestFor"),
        ("scheme/suggest", {"input": "H", "format": "banner"}, "format"),
        (
            "scheme/aggregate",
            {"inputs": ["H"], "format": "banner", "scope": "portion"},
            "format",
        ),
        (
            "scheme/aggregate",
            {"assertionSets": [], "format": "banner"},
            "format",
        ),
        ("scheme/diff", {"a": "H", "b": "L", "format": "banner"}, "format"),
    ],
)
def test_validator_rejects_removed_fields(
    spec: OpenApiRequestSchemas, route: str, body: Dict[str, Any], field: str
) -> None:
    errors = spec.validate("post", _ROUTE_PREFIX + route, body)
    assert any(f"'{field}'" in error for error in errors), errors


def test_validator_rejects_missing_required_field_and_wrong_type(
    spec: OpenApiRequestSchemas,
) -> None:
    missing = spec.validate(
        "post", _ROUTE_PREFIX + "scheme/process", {"surface": "portion"}
    )
    assert any("'input'" in error for error in missing), missing

    wrong_type = spec.validate(
        "post",
        _ROUTE_PREFIX + "scheme/render",
        {
            "assertions": [
                {
                    "categoryId": "level",
                    "conceptId": "HIGH",
                    "confidence": "sure",
                    "source": "parse",
                }
            ]
        },
    )
    assert wrong_type


def test_validator_accepts_the_renamed_fields(spec: OpenApiRequestSchemas) -> None:
    errors = spec.validate(
        "post",
        _ROUTE_PREFIX + "scheme/process",
        {
            "input": "H",
            "inputFormat": "portion",
            "outputFormat": "banner",
            "surface": "portion",
        },
    )
    assert errors == []


def test_validator_refuses_a_keyword_it_does_not_implement(
    spec: OpenApiRequestSchemas,
) -> None:
    with pytest.raises(NotImplementedError, match="'maxLength'"):
        spec._check("x", {"type": "string", "maxLength": 4}, "$", [])


@pytest.mark.parametrize(
    ("schema", "accepted", "refused"),
    [
        ({"type": "array", "minItems": 1}, ["a"], []),
        ({"type": "string", "pattern": "^#[0-9a-f]{3}$"}, "#fff", "white"),
        ({"not": {"required": ["snapshotId"]}}, {}, {"snapshotId": "s"}),
    ],
)
def test_validator_applies_the_keywords_response_schemas_use(
    spec: OpenApiRequestSchemas, schema: Any, accepted: Any, refused: Any
) -> None:
    assert spec._passes(accepted, schema, "$")
    assert not spec._passes(refused, schema, "$")


def test_a_closed_check_leaves_a_condition_open() -> None:
    # The shape SourceReference uses: an `if` that lists only the property it
    # tests. Closed like the object, it would be false here and the `then`
    # requiring `snapshotId` would never be enforced.
    probe = {
        "type": "object",
        "properties": {"reproducibility": {}, "snapshotId": {}, "providerId": {}},
        "if": {
            "properties": {"reproducibility": {"const": "reproducible"}},
            "required": ["reproducibility"],
        },
        "then": {"required": ["snapshotId"]},
    }
    spec = OpenApiRequestSchemas(
        {
            "components": {"schemas": {"Probe": probe}},
            "paths": {
                "/probe": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {}}}}
                    }
                }
            },
        }
    )
    source = {"reproducibility": "reproducible", "providerId": "nara"}
    assert spec.validate_closed("Probe", source) == [
        "$: required property 'snapshotId' is missing"
    ]
    assert spec.validate_closed("Probe", {**source, "snapshotId": "s1"}) == []
    assert spec.validate_closed("Probe", {**source, "snapshotId": "s1", "x": 1}) == [
        "$: property 'x' is not allowed by the contract"
    ]
