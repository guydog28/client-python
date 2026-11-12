"""Run the shared cache conformance plans against the Python client.

``vendor/spec/cache/v1/plans.json`` is the contract every EzClassify client
caches by. Each plan is one test here, so a failing plan names itself. Plans
that need a capability Python declares not applicable are checked for exactly
that, not skipped.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from ezclassify_rest_client import (
    EzClassifyContext,
    EzClassifyClientError,
    MalformedResponseError,
    RestClientCredentials,
    _response_cache,
)

from .cache_plans import (
    BASE_URL,
    NOT_APPLICABLE_CAPABILITIES,
    CountingReplay,
    PlanRun,
    _assert_error,
    load_plans,
)
from .wire_corpus import WireCorpus
from .wire_drivers import answered_in_process

PLANS = load_plans()
PLAN_BY_ID = {plan["id"]: plan for plan in PLANS["plans"]}


@pytest.mark.parametrize(
    "error",
    [
        EzClassifyClientError("HTTP error", status_code=500),
        EzClassifyClientError("connection failed"),
        ValidationError.from_exception_data("Probe", []),
    ],
    ids=["http", "connection", "raw-model-error"],
)
def test_malformed_response_expectation_refuses_unrelated_errors(
    error: Exception,
) -> None:
    with pytest.raises(AssertionError):
        _assert_error({"kind": "malformed-response"}, error, {})


def test_malformed_response_expectation_accepts_the_public_response_error() -> None:
    _assert_error(
        {"kind": "malformed-response"},
        MalformedResponseError("missing result", status_code=200, path="$.result"),
        {},
    )


def _applicable(plan: dict[str, Any]) -> bool:
    return not set(plan["capabilities"]) & set(NOT_APPLICABLE_CAPABILITIES)


RUNNABLE = [p["id"] for p in PLANS["plans"] if _applicable(p)]
DECLARED_ABSENT = [p["id"] for p in PLANS["plans"] if not _applicable(p)]


@pytest.fixture(scope="module")
def corpus() -> WireCorpus:
    return WireCorpus.vendored()


def test_the_plan_document_is_the_vendored_contract() -> None:
    assert PLANS["planVersion"] == "v1"
    assert PLANS["knownGaps"] == []
    assert len(PLANS["plans"]) == len(PLAN_BY_ID)


def test_only_capabilities_the_schema_allows_are_declared_absent() -> None:
    for name in NOT_APPLICABLE_CAPABILITIES:
        assert PLANS["capabilities"][name].get("notApplicable"), name
    required = set(PLANS["capabilities"]) - set(NOT_APPLICABLE_CAPABILITIES)
    assert required == {
        "responseGate",
        "clock",
        "scriptedResponses",
        "quiesce",
        "schemeResourceOperations",
    }


@pytest.mark.parametrize("plan_id", DECLARED_ABSENT)
def test_plans_needing_an_absent_capability_are_justified(plan_id: str) -> None:
    needed = set(PLAN_BY_ID[plan_id]["capabilities"]) & set(NOT_APPLICABLE_CAPABILITIES)
    assert needed
    methods = [
        member
        for owner in _public_operation_owners()
        for _, member in inspect.getmembers(owner, inspect.isfunction)
        if not member.__name__.startswith("_")
    ]
    if "cancellation" in needed:
        # No public operation takes a signal, token or context to cancel with.
        forbidden = {"cancel", "cancellation", "cancel_token", "token", "signal"}
        for method in methods:
            names = set(inspect.signature(method).parameters)
            assert not names & forbidden, f"{method.__qualname__} takes {names}"
    if "explicitNullMember" in needed:
        # An unset optional argument is omitted from the body, never sent null.
        # The unsetMember variant of key-canonical-members measures that.
        assert "key-canonical-members" in PLAN_BY_ID


def _public_operation_owners() -> list[type]:
    ctx = EzClassifyContext(
        BASE_URL,
        context_id="x",
        context_version="1.0.0",
        credentials=RestClientCredentials(context_token="t"),
    )
    owners = [type(group) for group in (ctx.scheme, ctx.guide, ctx.access)]
    owners += [type(ctx.document), type(ctx.crosswalk)]
    ctx.close()
    return owners


@pytest.mark.parametrize("plan_id", RUNNABLE)
def test_plan(
    corpus: WireCorpus, monkeypatch: pytest.MonkeyPatch, plan_id: str
) -> None:
    plan = PLAN_BY_ID[plan_id]
    replay = CountingReplay(corpus, PLANS["denialCase"])
    clock = [1_000.0]
    monkeypatch.setattr(_response_cache, "monotonic", lambda: clock[0])
    run = PlanRun(plan, PLANS, corpus, replay, clock)

    with answered_in_process(replay.handle):
        run.ctx = run.build_client()
        replay.reset_counts()
        try:
            run.run()
        finally:
            run.ctx.close()


def test_every_plan_is_accounted_for() -> None:
    assert set(RUNNABLE) | set(DECLARED_ABSENT) == set(PLAN_BY_ID)


def test_checklist_items_every_executed_plan_leaves_uncovered() -> None:
    """C07 and C08 are measured by cancellation plans only."""
    executed = [p for p in PLANS["plans"] if p["id"] in RUNNABLE]
    covered = {item for plan in executed for item in plan["covers"]}
    declared = {item["id"] for item in PLANS["checklist"]}
    assert declared - covered == {"C07", "C08"}
