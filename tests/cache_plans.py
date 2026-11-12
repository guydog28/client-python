"""Harness that runs the shared cache conformance plans against the Python client.

``vendor/spec/cache/v1/plans.json`` is the contract: every port runs the same
plans over the same wire corpus. This module supplies what a plan needs from a
port (see ``CACHE-SEMANTICS.md``, "Running the plans"):

* case drivers, which reuse the public drivers of the corpus replay suite;
* a counting replay transport that matches method, path and canonical body,
  with the version segment and query order allowed to vary;
* one cache-enabled client per plan, built with a static context carrier and
  connected before counting starts;
* a response gate, an observed join of concurrent callers, a clock the cache
  reads, scripted responses derived from recorded bytes, and a quiesce step.

Python's public operations take no cancellation signal, its request types
cannot carry an explicit null, and it has one method per operation over a
route and body, so those three capabilities are declared not applicable, with
the reason the plan schema fixes for each.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from ezclassify_rest_client import (
    EzClassifyClientError,
    MalformedResponseError,
    EzClassifyContext,
    RestClientCredentials,
    connect_context,
)

from .wire_corpus import WireCase, WireCorpus, request_key
from .wire_drivers import _CARRIER, run_context, wire_value

CACHE_DIR = Path(__file__).resolve().parents[1] / "vendor/spec/cache/v1"
BASE_URL = "http://replay.invalid"
RESOLVED_HEADER = "x-ezclassify-resolved-version"
STEP_TIMEOUT = 10.0

# Capabilities Python declares absent, with the only reason the schema allows.
NOT_APPLICABLE_CAPABILITIES = (
    "cancellation",
    "explicitNullMember",
)

_VERSION_PLACEHOLDER = "{version}"


def load_plans() -> dict[str, Any]:
    """Read the vendored plan document."""
    plans = json.loads((CACHE_DIR / "plans.json").read_text())
    assert isinstance(plans, dict)
    return plans


# ---------------------------------------------------------------------------
# Operations: the plan's operation names mapped to the public Python method a
# case is sent through. The route and body shape are checked so a driver can
# never run a case through the wrong operation.
# ---------------------------------------------------------------------------


def _body(case: WireCase) -> dict[str, Any]:
    assert isinstance(case.body, dict)
    return case.body


# Operation name -> predicate on the case body that says the Python method
# bound to the operation is the one that sends this case. Where two plan
# operations share a route, Python has one method for each body: access.check
# sends structured assertions and access.check_by_marking sends a marking, so
# the plans' access.check is the first and context.checkAccess the second.
_BODY_SHAPE: dict[str, Callable[[dict[str, Any]], bool]] = {
    "scheme.aggregate": lambda body: "inputs" in body,
    "scheme.aggregateAssertions": lambda body: "assertionSets" in body,
    "guide.evaluate": lambda body: "selections" not in body,
    "access.check": lambda body: "assertions" in body,
    "context.checkAccess": lambda body: "marking" in body,
}


def _check_driver(operation: str, route: str, case: WireCase) -> None:
    """Refuse to run a case through an operation it does not belong to."""
    path = urlsplit(case.path).path
    assert path.endswith("/" + route) or (route == "" and path.count("/") <= 4), (
        f"{operation} posts {route}, but {case.id} is {case.method} {path}"
    )
    shape = _BODY_SHAPE.get(operation)
    if shape is None:
        return
    assert shape(_body(case)), (
        f"{operation} is bound to a Python method that does not send {case.id}"
    )


# ---------------------------------------------------------------------------
# Replay transport.
# ---------------------------------------------------------------------------


class _Gate:
    def __init__(self) -> None:
        self.arrived = threading.Event()
        self.release = threading.Event()


def _normalize(path: str, versions: set[str]) -> str:
    """Replace the version segment with a placeholder, or insert one if absent.

    A client may carry the binding's version, the resolved version, or no
    version at all under a token-defaulted binding. The Context list and the
    version list (four segments or fewer) have none to normalize.
    """
    parts = path.split("/")
    # ['', 'v1', 'ctx', '<id>', ...]
    if len(parts) < 5 or parts[1:3] != ["v1", "ctx"]:
        return path
    if parts[4] in versions or re.fullmatch(r"\d+\.\d+\.\d+\S*", parts[4]):
        parts[4] = _VERSION_PLACEHOLDER
    elif parts[4] != "":
        parts.insert(4, _VERSION_PLACEHOLDER)
    return "/".join(parts)


class CountingReplay:
    """Answer requests with the recorded response of the matching case.

    Counts requests per case, holds gated cases until released, and applies
    scripted responses, which are always derived from the recorded bytes.
    """

    def __init__(self, corpus: WireCorpus, denial_case: str) -> None:
        self.corpus = corpus
        self.denial = corpus.by_id[denial_case]
        self.counts: Counter[str] = Counter()
        self.gates: dict[str, _Gate] = {}
        self.malformed: dict[str, list[str]] = {}
        self.denials: Counter[str] = Counter()
        self.resolved_version: str | None = None
        self.unmatched: list[str] = []
        self._lock = threading.Lock()
        self._versions: set[str] = set()
        self._index: dict[tuple[str, str, str], WireCase] = {}

    def index(self) -> None:
        """Index the corpus under the bound version allowance.

        Two cases that cannot be told apart would make a plan ambiguous, so
        the later one is refused instead of shadowed.
        """
        self._index.clear()
        for case in self.corpus.cases:
            # The plans run a client holding a context token; recordings made
            # under another credential class (the denial cases) repeat the
            # same requests and answer them differently.
            if case.credential != "context-token":
                continue
            key = self._case_key(case)
            assert key not in self._index, f"{case.id} duplicates {self._index[key].id}"
            self._index[key] = case

    def _case_key(self, case: WireCase) -> tuple[str, str, str]:
        return self._key(case.method, case.path, case.body, case.has_body)

    def _key(
        self, method: str, target: str, body: object, has_body: bool
    ) -> tuple[str, str, str]:
        path, _, query = target.partition("?")
        normalized = _normalize(path, self._versions)
        if query:
            normalized += "?" + query
        return request_key(method, normalized, body, has_body)

    def bind(self, versions: set[str]) -> None:
        """Say which version segments the client under test may send."""
        self._versions = set(versions)
        self.index()

    def reset_counts(self) -> None:
        self.counts.clear()

    def handle(self, request: httpx.Request) -> httpx.Response:
        has_body = bool(request.content)
        body = json.loads(request.content) if has_body else None
        key = self._key(
            request.method, request.url.raw_path.decode("ascii"), body, has_body
        )
        case = self._index.get(key)
        if case is None:
            self.unmatched.append(f"{key}")
            return httpx.Response(
                500,
                json={"error": "unrecorded_request", "detail": str(key)},
                request=request,
            )
        carrier = request.headers.get("x-ezclassify-context-token")
        assert carrier == _CARRIER, f"{case.id}: missing Context carrier"
        assert request.headers.get("authorization") is None
        with self._lock:
            self.counts[case.id] += 1
            gate = self.gates.get(case.id)
            malformed = self.malformed.pop(case.id, None)
            denial = self.denials[case.id] > 0
            if denial:
                self.denials[case.id] -= 1
        if gate is not None:
            gate.arrived.set()
            assert gate.release.wait(STEP_TIMEOUT), f"{case.id}: gate never released"
        return self._respond(request, case, malformed, denial)

    def _respond(
        self,
        request: httpx.Request,
        case: WireCase,
        malformed: list[str] | None,
        denial: bool,
    ) -> httpx.Response:
        source = self.denial if denial else case
        body = copy.deepcopy(source.response_body)
        headers = dict(source.response_headers)
        if malformed is not None:
            for pointer in malformed:
                _remove_pointer(body, pointer)
        if self.resolved_version is not None and not denial:
            headers[RESOLVED_HEADER] = self.resolved_version
            _rewrite_resolved(body, self.resolved_version)
        return httpx.Response(
            source.status,
            content=json.dumps(body).encode(),
            headers=headers,
            request=request,
        )


def _remove_pointer(body: Any, pointer: str) -> None:
    *parents, last = pointer.strip("/").split("/")
    node = body
    for name in parents:
        node = node[name]
    del node[last]


def _rewrite_resolved(body: Any, version: str) -> None:
    """Name a moved resolved version everywhere the recorded bytes name one."""
    if not isinstance(body, dict):
        return
    resolution = body.get("resolution")
    if isinstance(resolution, dict):
        resolution["resolvedVersion"] = version
        for artifact in resolution.get("artifacts", []):
            if artifact.get("kind") == "context":
                artifact["version"] = version
    if "schemes" in body and "version" in body:
        body["version"] = version


# ---------------------------------------------------------------------------
# Plan execution.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Outcome:
    value: object = None
    error: BaseException | None = None


class PlanRun:
    """Executes one plan's steps against a client built from its ``client`` block."""

    def __init__(
        self,
        plan: dict[str, Any],
        document: dict[str, Any],
        corpus: WireCorpus,
        replay: CountingReplay,
        clock: list[float],
    ) -> None:
        self.plan = plan
        self.routes = {op["name"]: op["route"] for op in document["operations"]}
        self.corpus = corpus
        self.replay = replay
        self.clock = clock
        self.ctx: EzClassifyContext | None = None
        self.outcomes: dict[str, _Outcome] = {}
        self.threads: dict[str, list[threading.Thread]] = {}
        self.joined: Counter[str] = Counter()

    # -- client ------------------------------------------------------------

    def build_client(self) -> EzClassifyContext:
        spec = self.plan["client"]
        binding = spec["binding"]
        version = {"pinned": "1.0.0", "unpinned": "latest", "token-defaulted": None}[
            binding
        ]
        # A token-defaulted client has no version of its own, so it asks for the
        # Context description at ``latest``; operations carry no segment.
        self.replay.bind({v for v in (version, "1.0.0", "latest") if v})
        return connect_context(
            BASE_URL,
            context_id=spec.get("context", "ez-full"),
            context_version=version,
            credentials=RestClientCredentials(context_token=_CARRIER),
        )

    # -- calls ---------------------------------------------------------------

    def _case(self, case_id: str, step: dict[str, Any]) -> WireCase:
        case = self.corpus.by_id[case_id]
        variant = step.get("variant")
        if variant == "reorderedMembers":
            return dataclasses.replace(case, body=_reversed_members(case.body))
        if variant == "unsetMember":
            body = dict(_body(case))
            body.pop(step["member"], None)
            return dataclasses.replace(case, body=body)
        assert variant is None, f"unsupported variant {variant}"
        return case

    def _invoke(self, step: dict[str, Any]) -> object:
        assert self.ctx is not None
        operation = step["operation"]
        case = self._case(step["case"], step)
        _check_driver(operation, self.routes[operation], case)
        return run_context(case, self.ctx)

    def _run_call(self, step: dict[str, Any]) -> None:
        expected = step.get("expect", {}).get("error")
        outcome = _Outcome()
        for _ in range(step.get("times", 1)):
            outcome = _Outcome()
            try:
                outcome.value = self._invoke(step)
            except AssertionError:
                raise
            except Exception as error:  # noqa: BLE001  the plan names the error
                outcome.error = error
            if expected is None:
                assert outcome.error is None, f"{step}: {outcome.error!r}"
            else:
                _assert_error(expected, outcome.error, step)
        if "caller" in step:
            self.outcomes[step["caller"]] = outcome

    def _run_concurrent(self, step: dict[str, Any]) -> None:
        case_id = step["case"]
        callers = step["callers"]
        for name in callers:
            self.outcomes[name] = _Outcome()
            thread = threading.Thread(
                target=self._caller, args=(name, step), daemon=True
            )
            self.threads.setdefault(case_id, []).append(thread)
            thread.start()
        self.joined[case_id] += len(callers)
        gate = self.replay.gates.get(case_id)
        if gate is None:
            for thread in self.threads[case_id][-len(callers) :]:
                thread.join(STEP_TIMEOUT)
            return
        assert gate.arrived.wait(STEP_TIMEOUT), f"{case_id}: request never arrived"
        assert self.ctx is not None
        cache = self.ctx._response_cache
        # One caller owns the request; the rest must be seen waiting on it.
        wanted = self.joined[case_id] - 1
        deadline = threading.Event()
        timer = threading.Timer(STEP_TIMEOUT, deadline.set)
        timer.start()
        try:
            while cache.waiting() < wanted and not deadline.is_set():
                deadline.wait(0.005)
        finally:
            timer.cancel()
        assert cache.waiting() == wanted, (
            f"{case_id}: {cache.waiting()} callers joined, expected {wanted}"
        )

    def _caller(self, name: str, step: dict[str, Any]) -> None:
        outcome = self.outcomes[name]
        try:
            outcome.value = self._invoke(step)
        except Exception as error:  # noqa: BLE001  recorded for the expect step
            outcome.error = error

    # -- steps ---------------------------------------------------------------

    def run(self) -> None:
        for step in self.plan["steps"]:
            getattr(self, "_step_" + step["step"])(step)
        for threads in self.threads.values():
            assert not any(t.is_alive() for t in threads), "a caller never settled"
        assert not self.replay.unmatched, self.replay.unmatched

    def _step_call(self, step: dict[str, Any]) -> None:
        self._run_call(step)

    def _step_concurrent(self, step: dict[str, Any]) -> None:
        self._run_concurrent(step)

    def _step_gate(self, step: dict[str, Any]) -> None:
        self.replay.gates[step["case"]] = _Gate()

    def _step_release(self, step: dict[str, Any]) -> None:
        case_id = step["case"]
        gate = self.replay.gates.pop(case_id)
        gate.release.set()
        for thread in self.threads.get(case_id, []):
            thread.join(STEP_TIMEOUT)
            assert not thread.is_alive(), f"{case_id}: a caller never settled"
        self.joined[case_id] = 0

    def _step_advanceClock(self, step: dict[str, Any]) -> None:
        self.clock[0] += step["ms"] / 1000.0

    def _step_respond(self, step: dict[str, Any]) -> None:
        kind = step["synthetic"]
        if kind == "malformed-success":
            self.replay.malformed[step["case"]] = list(step["removeMembers"])
        elif kind == "denial-404":
            self.replay.denials[step["case"]] += 1
        else:
            assert kind == "resolved-version"
            self.replay.resolved_version = step["version"]

    def _step_quiesce(self, step: dict[str, Any]) -> None:
        # The Python client holds no connection state and starts no background
        # work after a response, so there is nothing to wait for. Prove it.
        for threads in self.threads.values():
            assert not any(t.is_alive() for t in threads)

    def _step_mutateResult(self, step: dict[str, Any]) -> None:
        _mutate(self.outcomes[step["caller"]].value)

    def _step_expectOk(self, step: dict[str, Any]) -> None:
        for name in step["callers"]:
            outcome = self.outcomes[name]
            assert outcome.error is None, f"{name}: {outcome.error!r}"

    def _step_expectError(self, step: dict[str, Any]) -> None:
        for name in step["callers"]:
            _assert_error(step["error"], self.outcomes[name].error, step)

    def _step_expectWireCount(self, step: dict[str, Any]) -> None:
        assert "variant" not in step, "explicit-null counts need the null capability"
        assert self.replay.counts[step["case"]] == step["count"], (
            f"{self.plan['id']}: {step['case']} reached the wire "
            f"{self.replay.counts[step['case']]} times, expected {step['count']}"
        )

    def _step_expectIndependentResults(self, step: dict[str, Any]) -> None:
        case = self.corpus.by_id[self.plan_case(step)]
        for name in step["callers"]:
            outcome = self.outcomes[name]
            assert outcome.error is None
            assert wire_value(outcome.value) == case.response_body, (
                f"caller {name} holds a result that differs from its response"
            )

    def plan_case(self, _step: dict[str, Any]) -> str:
        """The case an independence check compares against: the plan's only one."""
        cases = {s["case"] for s in self.plan["steps"] if "case" in s}
        assert len(cases) == 1, "independence plans use a single case"
        return cases.pop()


def _assert_error(
    expected: dict[str, Any], error: BaseException | None, step: dict[str, Any]
) -> None:
    assert error is not None, f"{step}: expected {expected}, but the call succeeded"
    kind = expected["kind"]
    if kind == "http":
        assert isinstance(error, EzClassifyClientError), repr(error)
        assert error.status_code == expected["status"], repr(error)
    elif kind == "malformed-response":
        assert isinstance(error, MalformedResponseError), repr(error)
    else:
        raise AssertionError(f"python declares {kind!r} not applicable")


def _reversed_members(value: object) -> object:
    """Rebuild every mapping with its members in the opposite order."""
    if isinstance(value, dict):
        return {k: _reversed_members(v) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reversed_members(item) for item in value]
    return value


def _mutate(value: object) -> None:
    """Change a result in place, nested collections included."""
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            inner = getattr(value, name)
            if isinstance(inner, (BaseModel, list, dict)):
                _mutate(inner)
            elif isinstance(inner, str):
                setattr(value, name, inner + "-mutated")
    elif isinstance(value, list):
        for item in value:
            _mutate(item)
        value.append("mutated")
    elif isinstance(value, dict):
        for item in list(value.values()):
            _mutate(item)
        value["mutated"] = True


__all__ = [
    "BASE_URL",
    "CACHE_DIR",
    "NOT_APPLICABLE_CAPABILITIES",
    "CountingReplay",
    "PlanRun",
    "load_plans",
]
