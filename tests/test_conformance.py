"""Conformance runner for the EzClassify Python SDK.

Reads every engine-slice plan from the vendored spec's vendor/spec/plans/v1/,
pre-populates a local HTTP replayer with the matching recorded responses from
vendor/spec/recordings/v1/, and runs each plan case against the replayer.

Server-slice plans (ctx* methods) run against a live server through
``make conformance-server``.

Run with: pytest tests/test_conformance.py (from the repository root)
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from ezclassify._replayer import Replayer, _stable_json, recording_key

_ENGINE_SPEC = Path(__file__).parent.parent / "vendor" / "spec"
_PLANS_DIR = _ENGINE_SPEC / "plans" / "v1"
_FIXTURES_DIR = _ENGINE_SPEC / "fixtures" / "v1"
_RECORDINGS_DIR = _ENGINE_SPEC / "recordings" / "v1"

# Guide and access operations are reachable only through a bound Context. A
# guide or access policy is meaningless without a scheme to bind it to, so the
# REST API serves no standalone guide/access routes. Those cases route
# through /v1/ctx/{ctxId}/{version}/... with payload-only bodies. The replayer
# is keyed by (path, body) and never resolves a live context; _context_base
# builds the test-only Context path for each fixture composition.

# Number of engine-slice plan cases this runner must execute against the
# vendored spec bundle. Engine-only registry vectors are outside the HTTP
# adapter's contract; all other cases run. The count is a pinned golden: when
# the vendored bundle deliberately adds or removes plan cases, update it in the
# same commit. Without the pin, a missing recording or unreadable fixture would
# silently shrink the suite.
_EXPECTED_CASE_COUNT = 146


def _context_base(fixture: Any, guide_fixture: str) -> str:
    """Return a unique test-only Context path for one fixture composition.

    The request body carries no loose scheme/layer selectors. Encoding
    the fixture identity in this synthetic Context id prevents recordings for
    two different compositions with the same operation body from colliding.
    """
    identity = _stable_json({"fixture": fixture, "guideFixture": guide_fixture})
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return f"/v1/ctx/conformance-{digest}/1.0.0"


def _recording_key(
    method: str, args: Any, fixture: Any, mode: str, ctx_id: str, ctx_version: str
) -> str:
    """Compute the recording lookup key using the canonical hash algorithm."""
    raw = (
        method
        + "|"
        + _stable_json(args)
        + "|"
        + _stable_json(fixture)
        + "|"
        + mode
        + "|"
        + ctx_id
        + "|"
        + ctx_version
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_all_recordings() -> dict[str, Any]:
    """Return a flat map of recording-key → response for all recordings files."""
    result: dict[str, Any] = {}
    for path in sorted(_RECORDINGS_DIR.glob("*.recordings.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, entry in data.get("responses", {}).items():
            result[key] = entry["response"]
    return result


def _load_fixture(name: str) -> dict:
    """Load a fixture JSON file from vendor/spec/fixtures/v1/."""
    return json.loads((_FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _scheme_id_from_fixture(name: str) -> str:
    """Extract the scheme ID from a fixture file."""
    data = _load_fixture(name)
    return data["scheme"]["id"]


def _guide_id_from_fixture(name: str) -> str:
    """Extract the guide ID from a guide fixture file."""
    data = _load_fixture(name)
    if "guide" in data and isinstance(data["guide"], dict):
        return data["guide"].get("id", name)
    return data.get("id", name)


def _build_plan_body(
    method: str,
    args: list,
    fixture: Any,
    guide_fixture: str,
) -> tuple[str, dict, tuple[str, str] | None]:
    """Construct the HTTP API path and request body for a plan case.

    Returns (path, body, verdict). verdict is None when the case must execute,
    ("skip", reason) for a plan-declared skip (context-only methods and methods
    this runner does not route), or ("drop", reason) for a corpus defect (a
    missing or unreadable fixture) that must fail the suite by name instead of
    vanishing.
    """
    ctx_base = _context_base(fixture, guide_fixture)

    if method in ("ctxProcess", "ctxScan", "ctxDocumentAudit"):
        return (
            "",
            {},
            ("skip", f"context-only method {method!r} is not routed by this runner"),
        )

    def str_arg(i: int) -> str:
        if i < len(args) and isinstance(args[i], str):
            return args[i]
        return ""

    def plan_options(body: dict, i: int = 1) -> dict:
        """Carry canonical options without overwriting an operand."""
        if i < len(args) and isinstance(args[i], dict):
            for key, value in args[i].items():
                if key in body and body[key] != value:
                    raise ValueError(f"Conflicting plan option: {key}")
                body[key] = value
        return body

    if method in ("registryProcessAll", "registrySuggestAcross"):
        return "", {}, ("skip", "loose registry operations are not public SDK routes")

    if method == "checkAccess":
        # The access policy is bound to the context; the body carries only the
        # data assertions and the subject's user attributes.
        data_assertions = args[0] if args else []
        user_attrs = args[1] if len(args) > 1 else {}
        body = {"assertions": data_assertions, "userAttributes": user_attrs}
        return f"{ctx_base}/access/check", body, None

    if method in ("evaluateGuide", "evaluateMany", "guideScan"):
        # A guide case without a readable guide fixture is a corpus defect.
        gf = guide_fixture or (fixture if isinstance(fixture, str) else "")
        if not gf:
            return "", {}, ("drop", f"guide case {method!r} without a guide fixture")
        try:
            guide_id = _guide_id_from_fixture(gf)
        except FileNotFoundError:
            return "", {}, ("drop", f"unreadable guide fixture: {gf!r}")

        if method == "guideScan":
            body = {"text": str_arg(0), "guideId": guide_id}
            return f"{ctx_base}/guide/scan", body, None

        # evaluateGuide names the plan's guide; evaluateMany sends the plan's
        # selections, each already naming its guide.
        selected = args[0] if args and isinstance(args[0], list) else []
        if method == "evaluateMany":
            return f"{ctx_base}/guide/evaluate", {"selections": selected}, None
        body = {"guideId": guide_id, "selectedRuleIds": selected}
        return f"{ctx_base}/guide/evaluate", body, None

    # Validate the referenced fixture even though the Context route owns its
    # scheme selection. An unreadable fixture is still a corpus defect.
    try:
        if isinstance(fixture, list):
            [_scheme_id_from_fixture(n) for n in fixture]
        else:
            _scheme_id_from_fixture(fixture)
    except (FileNotFoundError, KeyError) as exc:
        return "", {}, ("drop", f"unreadable scheme fixture {fixture!r}: {exc!r}")

    if method == "process":
        # process() accepts either a marking string or an already-parsed
        # assertion array as its first argument. The assertion-array form is
        # how scope-only and capture-value markings enter the pipeline
        # losslessly; no rendered string can carry them. The process request
        # always carries the typed text, so an array goes out as the facts
        # already chosen beside an empty `input`, as the client sends it.
        if args and isinstance(args[0], list):
            body: dict = {"input": "", "assertions": args[0]}
        else:
            body = {"input": str_arg(0)}
        body = plan_options(body)
        return f"{ctx_base}/scheme/process", body, None

    if method == "validate":
        # validate carries the marking as text or as facts, exactly one.
        if args and isinstance(args[0], list):
            validate_body: dict = {"assertions": args[0]}
        else:
            validate_body = {"input": str_arg(0)}
        validate_body = plan_options(validate_body)
        return f"{ctx_base}/scheme/validate", validate_body, None

    if method == "suggest":
        if args and isinstance(args[0], list):
            suggest_body: dict = {"assertions": args[0]}
        else:
            suggest_body = {"input": str_arg(0)}
        return f"{ctx_base}/scheme/suggest", plan_options(suggest_body), None

    if method == "normalize":
        return f"{ctx_base}/scheme/normalize", plan_options({"input": str_arg(0)}), None

    if method == "render":
        render_body: dict = {"assertions": args[0] if args else []}
        if len(args) > 1 and isinstance(args[1], str) and args[1]:
            render_body["format"] = args[1]
        return f"{ctx_base}/scheme/render", render_body, None

    if method == "scan":
        return f"{ctx_base}/scheme/scan", plan_options({"text": str_arg(0)}), None

    if method == "aggregate":
        inputs = args[0] if args and isinstance(args[0], list) else []
        agg_body: dict = {"inputs": inputs}
        agg_body = plan_options(agg_body)
        return f"{ctx_base}/scheme/aggregate", agg_body, None

    if method == "aggregateAssertions":
        # The assertion-set aggregate path: arg0 is a list of assertion sets
        # (one inner array per marking), carried on the wire as `assertionSets`,
        # mutually exclusive with `inputs`. It transports scope-only
        # assertions and capture values that the string `inputs` path drops.
        sets = args[0] if args and isinstance(args[0], list) else []
        aa_body: dict = {"assertionSets": sets}
        aa_body = plan_options(aa_body)
        return f"{ctx_base}/scheme/aggregate", aa_body, None

    if method == "diff":
        return (
            f"{ctx_base}/scheme/diff",
            plan_options({"a": str_arg(0), "b": str_arg(1)}, i=2),
            None,
        )

    return "", {}, ("skip", f"method {method!r} is not routed by this runner")


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


def test_subset_match_reads_an_object_against_an_array_by_index_and_length():
    spans = [{"inner": "A", "start": 0}, {"inner": "B", "start": 9}]
    assert _subset_match(spans, {"1": {"inner": "B"}, "length": 2})
    assert not _subset_match(spans, {"length": 1})
    assert not _subset_match([], {"0": {"inner": "A"}})
    assert not _subset_match(spans, {"01": {"inner": "B"}})


def test_subset_match_rejects_boolean_for_expected_number():
    # isinstance(True, int) is true, so a boolean actual must be refused
    # explicitly for an expected numeric field.
    assert not _subset_match(True, 1)
    assert not _subset_match(False, 0)
    assert _subset_match(1, 1)
    assert _subset_match(True, True)
    assert not _subset_match(1, True)


def _collect_cases() -> list[tuple[str, dict]]:
    """Collect all engine-slice plan cases as (plan_name, case_dict) pairs."""
    cases: list[tuple[str, dict]] = []
    for plan_path in sorted(_PLANS_DIR.glob("*.json")):
        if plan_path.name in ("plan-schema.json", "registry.json"):
            continue
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("slice") != "engine":
            continue
        for tc in plan.get("cases", []):
            cases.append((plan_path.stem, tc))

    return cases


def _make_test_id(plan_name: str, tc: dict) -> str:
    return f"{plan_name}/{tc.get('name', '?')}"


def _build_replayer_map() -> dict[str, dict]:
    """Pre-populate the replayer recording map from vendor/spec/recordings/v1/."""
    all_recordings = _load_all_recordings()
    replayer_map: dict[str, dict] = {}

    for _plan_name, tc in _collect_cases():
        method = tc.get("method", "")
        args = tc.get("args", [])
        fixture = tc.get("fixture")
        mode = tc.get("mode", "fromJSON")
        ctx_id = tc.get("ctxId", "")
        ctx_version = tc.get("ctxVersion", "")
        guide_fixture = tc.get("guideFixture", "")

        rec_key = _recording_key(method, args, fixture, mode, ctx_id, ctx_version)
        response = all_recordings.get(rec_key)
        if response is None:
            continue

        api_path, body, verdict = _build_plan_body(method, args, fixture, guide_fixture)
        if verdict is not None:
            continue

        rk = recording_key(api_path, body)
        entry = {"statusCode": 200, "body": response}
        if rk in replayer_map and _stable_json(replayer_map[rk]) != _stable_json(entry):
            raise ValueError(
                f"Conflicting recordings for request: {_make_test_id(_plan_name, tc)}"
            )
        replayer_map[rk] = entry

    return replayer_map


_REPLAYER_MAP = _build_replayer_map()
_REPLAYER: Replayer | None = None


@pytest.fixture(scope="session", autouse=True)
def _session_replayer():
    """Start a single shared replayer for all conformance tests."""
    global _REPLAYER
    _REPLAYER = Replayer(_REPLAYER_MAP)
    yield _REPLAYER
    _REPLAYER.close()
    _REPLAYER = None


def _get_replayer_url() -> str:
    assert _REPLAYER is not None, "replayer not started"
    return _REPLAYER.url


def _post_case(api_path: str, body: dict) -> tuple[int, Any]:
    """Send one built plan case to the replayer and return (status, parsed_body)."""
    url = _get_replayer_url() + api_path
    body_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize test_conformance_case with all engine-slice plan entries."""
    if "plan_name" in metafunc.fixturenames and "test_case" in metafunc.fixturenames:
        cases = _collect_cases()
        ids = [_make_test_id(pn, tc) for pn, tc in cases]
        metafunc.parametrize("plan_name,test_case", cases, ids=ids)


def test_conformance_case(
    plan_name: str, test_case: dict, _session_replayer: Replayer
) -> None:
    """Run one engine-slice plan case against the replayer and subset-match the result."""
    method = test_case.get("method", "")
    args = test_case.get("args", [])
    fixture = test_case.get("fixture")
    guide_fixture = test_case.get("guideFixture", "")
    expect = test_case.get("expect")

    api_path, body, verdict = _build_plan_body(method, args, fixture, guide_fixture)

    if verdict is not None:
        kind, reason = verdict
        if kind == "drop":
            # A case that lost its fixture is corpus corruption; fail by name
            # instead of letting the case vanish.
            pytest.fail(
                f"case dropped instead of executed: {reason} "
                f"(plan={plan_name}, test={test_case.get('name')})"
            )
        pytest.fail(
            f"unsupported engine plan: {reason} "
            f"(plan={plan_name}, test={test_case.get('name')})"
        )

    status, actual = _post_case(api_path, body)

    if (
        status == 404
        and isinstance(actual, dict)
        and actual.get("error") == "no_recording"
    ):
        # A missing recording is corpus corruption, not an expected skip.
        pytest.fail(
            f"no recording for path={actual.get('path')} body_hash={actual.get('bodyHash')} "
            f"(plan={plan_name}, test={test_case.get('name')}); the case must execute, "
            f"not silently drop out of the suite"
        )

    assert status == 200, (
        f"expected 200, got {status}: {json.dumps(actual)}\n"
        f"  plan={plan_name}, test={test_case.get('name')}"
    )

    assert _subset_match(actual, expect), (
        f"Subset-match failed.\n"
        f"  plan:     {plan_name}\n"
        f"  test:     {test_case.get('name')}\n"
        f"  actual:   {json.dumps(actual, indent=2)}\n"
        f"  expected: {json.dumps(expect, indent=2)}"
    )


def test_executed_case_count() -> None:
    """Guard the suite against silent shrinkage.

    Every collected HTTP case must execute. Engine-only registry ownership is
    checked separately, so new methods cannot silently reduce this count.
    """
    executed = []
    for plan_name, tc in _collect_cases():
        _, _, verdict = _build_plan_body(
            tc.get("method", ""),
            tc.get("args", []),
            tc.get("fixture"),
            tc.get("guideFixture", ""),
        )
        assert verdict is None, (
            f"unexecutable HTTP case: {plan_name}/{tc['name']}: {verdict}"
        )
        executed.append(_make_test_id(plan_name, tc))
    assert len(executed) == _EXPECTED_CASE_COUNT, (
        f"Executed conformance case count ({len(executed)}) drifted from the pinned "
        f"corpus count ({_EXPECTED_CASE_COUNT}); if the vendored spec bundle changed "
        f"deliberately, update _EXPECTED_CASE_COUNT in the same commit"
    )


@pytest.mark.parametrize("facts", [[], [{"categoryId": "grade", "conceptId": "OPEN"}]])
def test_suggest_fact_input_has_no_synthesized_text(facts: list) -> None:
    _, body, verdict = _build_plan_body("suggest", [facts], "ref-scheme-1", "")
    assert verdict is None
    assert body == {"assertions": facts}


@pytest.mark.parametrize("method", ["process", "validate", "aggregate"])
def test_plan_context_and_read_output_options_reach_request(method: str) -> None:
    value = ["LOW"] if method == "aggregate" else "LOW"
    context = {"role": "part", "partOf": {"rendered": "LOW", "assertions": []}}
    options = {
        "context": context,
        "inputFormat": "short",
        "outputFormat": "default",
        "surface": "marking",
    }
    _, body, verdict = _build_plan_body(method, [value, options], "ref-scheme-1", "")
    assert verdict is None
    input_key = "inputs" if method == "aggregate" else "input"
    assert body == {input_key: value, **options}


def test_process_plan_parts_and_chosen_facts_reach_request() -> None:
    options = {"parts": ["H"], "assertions": [], "outputs": [], "suggestFor": []}
    _, body, verdict = _build_plan_body("process", ["LOW", options], "ref-scheme-1", "")
    assert verdict is None
    assert body == {"input": "LOW", **options}


def test_validate_fact_input_keeps_context_without_input_format() -> None:
    context = {"role": "part", "partOf": {"rendered": "LOW"}}
    _, body, verdict = _build_plan_body(
        "validate", [[], {"context": context}], "ref-scheme-1", ""
    )
    assert verdict is None
    assert body == {"assertions": [], "context": context}


def test_suggest_options_retain_explicit_empty_filter_and_false_include_gated() -> None:
    options = {
        "inputFormat": "short",
        "outputFormat": "default",
        "surface": "marking",
        "filter": "",
        "includeGated": False,
    }
    _, body, verdict = _build_plan_body("suggest", ["LOW", options], "ref-scheme-1", "")
    assert verdict is None
    assert body == {"input": "LOW", **options}


def test_plan_options_cannot_overwrite_input_operand() -> None:
    with pytest.raises(ValueError, match="Conflicting plan option: input"):
        _build_plan_body(
            "process",
            ["LOW", {"input": "other"}],
            "ref-scheme-1",
            "",
        )


def _synthetic_plan_recordings(same_response: bool) -> tuple[list, dict]:
    cases = [
        (
            "synthetic",
            {
                "name": "without-options",
                "method": "validate",
                "fixture": "ref-scheme-1",
                "args": ["LOW"],
            },
        ),
        (
            "synthetic",
            {
                "name": "empty-options",
                "method": "validate",
                "fixture": "ref-scheme-1",
                "args": ["LOW", {}],
            },
        ),
    ]
    recordings = {}
    for index, (_, case) in enumerate(cases):
        key = _recording_key(
            "validate", case["args"], case["fixture"], "fromJSON", "", ""
        )
        recordings[key] = {"valid": True if same_response else index == 0}
    return cases, recordings


def test_conflicting_recorded_request_identity_refuses_instead_of_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases, recordings = _synthetic_plan_recordings(False)
    monkeypatch.setitem(globals(), "_collect_cases", lambda: cases)
    monkeypatch.setitem(globals(), "_load_all_recordings", lambda: recordings)
    with pytest.raises(
        ValueError, match="Conflicting recordings for request: synthetic/empty-options"
    ):
        _build_replayer_map()


def test_equivalent_recorded_request_identity_keeps_same_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases, recordings = _synthetic_plan_recordings(True)
    monkeypatch.setitem(globals(), "_collect_cases", lambda: cases)
    monkeypatch.setitem(globals(), "_load_all_recordings", lambda: recordings)
    assert len(cases) == 2
    assert list(_build_replayer_map().values()) == [
        {"statusCode": 200, "body": {"valid": True}}
    ]


def test_registry_plan_is_owned_by_embedded_engine() -> None:
    """Ambient registry fan-out is intentionally absent from the HTTP SDK."""
    plan = json.loads((_PLANS_DIR / "registry.json").read_text())
    assert plan["slice"] == "engine"
    assert len(plan["cases"]) == 5
    assert {case["method"] for case in plan["cases"]} == {
        "registryProcessAll",
        "registrySuggestAcross",
    }


def test_unknown_plan_method_fails_execution_contract() -> None:
    """A new upstream method needs a driver before this HTTP suite can pass."""
    _, _, verdict = _build_plan_body("futureOperation", [], "ref-scheme-1", "")
    assert verdict is not None
    assert "futureOperation" in verdict[1]


def test_unknown_plan_case_fails_instead_of_reporting_a_skip() -> None:
    """Unsupported dispatch must make native verification fail, never shrink it."""
    try:
        test_conformance_case(
            "future",
            {"method": "futureOperation", "name": "new-op", "fixture": "ref-scheme-1"},
            None,
        )
    except (pytest.fail.Exception, pytest.skip.Exception) as error:
        assert isinstance(error, pytest.fail.Exception), type(error).__name__
        assert "futureOperation" in str(error)
    else:
        pytest.fail("unknown dispatch unexpectedly succeeded")
