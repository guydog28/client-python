"""Tests for ezclassify-rest-contract Pydantic models."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from ezclassify_rest_contract import (
    AccessDecision,
    AccessRuleResult,
    AggregateResult,
    Assertion,
    ContextSchemeAggregateResult,
    DiffResult,
    EvaluationResult,
    ExplanationTrace,
    GuideScanResult,
    GuideScanSpan,
    GuideRule,
    ProcessResult,
    ScanMatch,
    Suggestion,
    TraceEntry,
    TraceInference,
    TraceRepair,
    TraceValidationIssue,
    ValidateResult,
    ValidationError,
    EngineWarning,
)

_ASSESSMENT = {
    "emitted": [],
    "omitted": [],
    "collapsed": [],
    "conflicts": [],
    "unrepresentable": [],
}

# The members every reading of a marking answers, empty.
_NO_FINDINGS = {
    "assertions": [],
    "errors": [],
    "warnings": [],
    "appliedFixes": [],
    "notices": [],
}


def _validate_wire(**members: object) -> dict:
    """A validate result with every member the contract requires."""
    wire = {
        "valid": True,
        "inputWasValid": True,
        "rendered": "MED",
        "assessment": _ASSESSMENT,
        **_NO_FINDINGS,
    }
    wire.update(members)
    return wire


def _process_wire(**members: object) -> dict:
    """A process result: the validate result plus the authoring answers."""
    return _validate_wire(**{"renders": {}, "proposedFixes": [], **members})


def _aggregate_wire(**members: object) -> dict:
    """A rollup: a reading without the per-text verdict and assessment."""
    wire = {"valid": True, "rendered": "M", "proposedFixes": [], **_NO_FINDINGS}
    wire.update(members)
    return wire


class TestPublicSurface:
    def test_registry_and_warning_models_are_exported(self):
        # These names have no dedicated behavior tests below; assert they stay
        # importable from the package root so the public surface cannot shrink
        # silently.
        for model in (EngineWarning,):
            assert isinstance(model, type)


class TestAssertion:
    def test_from_dict_full(self):
        a = Assertion.from_dict(
            {
                "conceptId": "LEVEL_HIGH",
                "categoryId": "level",
                "confidence": "certain",
                "source": "parse",
                "value": "A&B",
            }
        )
        assert a.concept_id == "LEVEL_HIGH"
        assert a.category_id == "level"
        assert a.confidence == "certain"
        assert a.value == "A&B"

    def test_from_dict_minimal(self):
        a = Assertion.from_dict(
            {
                "conceptId": "X",
                "categoryId": "f",
                "confidence": "inferred",
                "source": "infer",
            }
        )
        assert a.expires_at is None
        assert a.value is None

    def test_model_validate_round_trip(self):
        data = {
            "conceptId": "C",
            "categoryId": "cat",
            "confidence": "certain",
            "source": "parse",
        }
        a = Assertion.model_validate(data)
        assert a.concept_id == "C"


class TestValidationError:
    def test_from_dict(self):
        e = ValidationError.from_dict(
            {"constraintId": "C1", "message": "Missing required"}
        )
        assert e.constraint_id == "C1"
        assert e.message == "Missing required"

    def test_optional_fields_default_none(self):
        e = ValidationError.from_dict({"constraintId": "C1", "message": "err"})
        assert e.severity is None
        assert e.category_id is None


class TestValidateResult:
    def test_from_dict(self):
        r = ValidateResult.from_dict(
            {
                "valid": True,
                "inputWasValid": False,
                "assertions": [],
                "errors": [],
                "warnings": [],
                "appliedFixes": [],
                "rendered": "MED",
                "assessment": _ASSESSMENT,
                "recognition": {
                    "status": "complete",
                    "inputFormat": "marking/long",
                    "role": "whole",
                    "surface": "marking",
                    "unmatched": [],
                },
                "notices": [],
            },
        )
        assert r.valid is True
        assert r.input_was_valid is False
        assert r.recognition is not None
        assert r.recognition["inputFormat"] == "marking/long"
        assert r.recognition["role"] == "whole"

    def test_carries_no_authoring_answers(self):
        fields = set(ValidateResult.model_fields)
        assert not fields & {
            "proposed_fixes",
            "renders",
            "suggestions_for",
            "assertions_before_repair",
        }

    @pytest.mark.parametrize("verdict", ["valid", "inputWasValid"])
    def test_a_missing_verdict_is_refused_not_defaulted(self, verdict):
        payload = _validate_wire()
        del payload[verdict]
        with pytest.raises(PydanticValidationError) as failure:
            ValidateResult.from_dict(payload)
        assert failure.value.errors()[0]["loc"] == (verdict,)


class TestVerdictsAreDecodedStrictly:
    """A verdict that is not a JSON boolean is a malformed result.

    Pydantic's lax mode would read ``"false"`` and ``0`` as False and ``"yes"``
    and ``1`` as True, which settles a malformed answer for the server, and in
    the True direction lets a broken result read as valid or granted.
    """

    _VALIDATE = _validate_wire()
    _AGGREGATE = _aggregate_wire()

    @pytest.mark.parametrize("value", ["false", "true", "yes", "off", 0, 1, None])
    @pytest.mark.parametrize(
        ("model", "payload", "verdict"),
        [
            (ValidateResult, _VALIDATE, "valid"),
            (ValidateResult, _VALIDATE, "inputWasValid"),
            (ProcessResult, _process_wire(), "valid"),
            (ProcessResult, _process_wire(), "inputWasValid"),
            (AggregateResult, _AGGREGATE, "valid"),
        ],
    )
    def test_a_verdict_that_is_not_a_boolean_is_refused(
        self, model, payload, verdict, value
    ):
        with pytest.raises(PydanticValidationError) as failure:
            model.from_dict({**payload, verdict: value})
        assert failure.value.errors()[0]["loc"] == (verdict,)

    @pytest.mark.parametrize("value", ["true", 1])
    def test_an_access_grant_that_is_not_a_boolean_is_refused(self, value):
        with pytest.raises(PydanticValidationError):
            AccessDecision.from_dict({"granted": value, "rules": [], "warnings": []})

    def test_a_boolean_verdict_decodes_as_sent(self):
        r = ValidateResult.from_dict({**self._VALIDATE, "valid": False})
        assert r.valid is False
        assert r.input_was_valid is True


class TestExplanationTrace:
    def test_from_dict(self):
        trace = ExplanationTrace.from_dict(
            {
                "input": "HIGH",
                "schemeId": "example-scheme",
                "entries": [
                    {
                        "stage": "infer",
                        "action": "add",
                        "detail": "Added STAFF: HIGH requires it.",
                        "conceptId": "audience-staff",
                        "ruleId": "high-needs-staff",
                    }
                ],
                "repairs": [
                    {
                        "ruleId": "upper-case",
                        "description": "Writes the level in capitals.",
                        "confidence": "safe",
                        "before": "high",
                        "after": "HIGH",
                        "cosmetic": True,
                    }
                ],
                "validationErrors": [
                    {"constraintId": "needs-staff", "message": "HIGH needs STAFF."}
                ],
                "inferences": [
                    {
                        "ruleId": "high-needs-staff",
                        "conceptId": "audience-staff",
                        "explanation": "HIGH requires STAFF.",
                    }
                ],
                "finalAssertions": [
                    {
                        "categoryId": "level",
                        "conceptId": "level-high",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "rendered": "HIGH//STAFF",
            }
        )
        assert trace.scheme_id == "example-scheme"
        entry = trace.entries[0]
        assert isinstance(entry, TraceEntry)
        assert (entry.stage, entry.action, entry.rule_id) == (
            "infer",
            "add",
            "high-needs-staff",
        )
        assert entry.concept_name is None
        repair = trace.repairs[0]
        assert isinstance(repair, TraceRepair)
        assert (repair.before, repair.after, repair.confidence) == (
            "high",
            "HIGH",
            "safe",
        )
        issue = trace.validation_errors[0]
        assert isinstance(issue, TraceValidationIssue)
        assert issue.constraint_id == "needs-staff"
        inference = trace.inferences[0]
        assert isinstance(inference, TraceInference)
        assert inference.explanation == "HIGH requires STAFF."
        assert trace.final_assertions[0].concept_id == "level-high"
        assert trace.rendered == "HIGH//STAFF"

    @pytest.mark.parametrize(
        ("member", "item", "missing"),
        [
            ("entries", {"stage": "parse", "action": "read"}, "detail"),
            (
                "repairs",
                {"ruleId": "r", "description": "d", "before": "a", "after": "A"},
                "confidence",
            ),
            ("validationErrors", {"constraintId": "c"}, "message"),
            ("inferences", {"ruleId": "r", "conceptId": "c"}, "explanation"),
        ],
    )
    def test_a_trace_item_missing_a_required_member_is_refused(
        self, member, item, missing
    ):
        trace = {
            "input": "H",
            "schemeId": "levels",
            "entries": [],
            "repairs": [],
            "validationErrors": [],
            "inferences": [],
            "finalAssertions": [],
            "rendered": "H",
            member: [item],
        }
        with pytest.raises(PydanticValidationError) as failure:
            ExplanationTrace.from_dict(trace)
        assert failure.value.errors()[0]["loc"] == (member, 0, missing)


class TestProcessResult:
    def test_from_dict(self):
        r = ProcessResult.from_dict(
            {
                "valid": True,
                "inputWasValid": True,
                "assessment": _ASSESSMENT,
                "assertions": [
                    {
                        "conceptId": "LEVEL_MED",
                        "categoryId": "level",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "errors": [],
                "rendered": "M",
                "renders": {},
                "warnings": [],
                "appliedFixes": [],
                "proposedFixes": [],
                "notices": [],
            },
        )
        assert r.valid is True
        assert len(r.assertions) == 1
        assert r.assertions[0].concept_id == "LEVEL_MED"
        assert r.rendered == "M"

    def test_named_outputs_and_category_options_decode(self):
        r = ProcessResult.from_dict(
            _process_wire(
                rendered="HIGH//STAFF",
                renders={
                    "marking/short": {"rendered": "H//STF", "assessment": _ASSESSMENT}
                },
                suggestionsFor={
                    "audience": {
                        "suggestions": [
                            {
                                "conceptId": "audience-staff",
                                "categoryId": "audience",
                                "label": "STAFF",
                                "description": "Staff only",
                                "name": "Staff",
                                "views": {"default": "STAFF"},
                                "group": "",
                                "selected": False,
                                "order": 0,
                            }
                        ],
                        "warnings": [],
                    }
                },
            )
        )
        assert r.renders["marking/short"]["rendered"] == "H//STF"
        assert r.suggestions_for is not None
        assert r.suggestions_for["audience"].suggestions[0].label == "STAFF"

    def test_category_options_are_absent_unless_asked_for(self):
        r = ProcessResult.from_dict(_process_wire(rendered="L"))
        assert r.suggestions_for is None
        assert r.renders == {}

    def test_is_a_validate_result_with_the_authoring_answers_added(self):
        # The contract defines a process result as the validate result plus
        # the authoring answers, so one goes wherever a validate result does,
        # and every field they share is declared once, on the base.
        assert issubclass(ProcessResult, ValidateResult)
        for name, field in ValidateResult.model_fields.items():
            shared = ProcessResult.model_fields[name]
            assert (shared.annotation, shared.alias, shared.is_required()) == (
                field.annotation,
                field.alias,
                field.is_required(),
            ), name
        assert set(ProcessResult.model_fields) - set(ValidateResult.model_fields) == {
            "assertions_before_repair",
            "proposed_fixes",
            "renders",
            "suggestions_for",
        }

    def test_a_process_result_stands_in_a_validate_result_position(self):
        process = ProcessResult.from_dict(_process_wire(rendered="H"))
        match = ScanMatch(
            start=0,
            end=1,
            marking="H",
            role="part",
            type="standalone",
            wrapped=False,
            result=process,
        )
        assert match.result is process


class TestSuggestion:
    def test_from_dict(self):
        s = Suggestion.from_dict(
            {
                "conceptId": "LEVEL_HIGH",
                "categoryId": "level",
                "label": "H",
                "description": "Level High",
                "name": "Level High",
                "group": "Level",
                "selected": False,
                "order": 3,
                "views": {"default": "H"},
            }
        )
        assert s.concept_id == "LEVEL_HIGH"
        assert s.label == "H"
        assert s.views["default"] == "H"


class TestAggregateResult:
    def test_from_dict(self):
        r = AggregateResult.from_dict(_aggregate_wire())
        assert r.rendered == "M"
        assert r.valid is True

    def test_a_missing_verdict_is_refused_not_defaulted(self):
        # An aggregate with no `valid` is malformed. Reading it as valid would
        # turn a rollup that carries errors into one that stands.
        with pytest.raises(PydanticValidationError) as failure:
            payload = _aggregate_wire(
                rendered="H", errors=[{"constraintId": "C1", "message": "err"}]
            )
            del payload["valid"]
            AggregateResult.from_dict(payload)
        assert failure.value.errors()[0]["loc"] == ("valid",)

    def test_a_missing_verdict_in_the_envelope_is_refused(self):
        with pytest.raises(PydanticValidationError) as failure:
            ContextSchemeAggregateResult.model_validate(
                {
                    "resolution": {
                        "contextId": "c",
                        "resolvedVersion": "1.0.0",
                        "artifacts": [],
                        "sources": [],
                    },
                    "operationLimitations": [],
                    "result": {
                        "rendered": "H",
                        "assertions": [],
                        "errors": [{"constraintId": "C1", "message": "err"}],
                        "warnings": [],
                        "appliedFixes": [],
                        "proposedFixes": [],
                        "notices": [],
                    },
                }
            )
        assert failure.value.errors()[0]["loc"] == ("result", "valid")


class TestDiffResult:
    def test_from_dict(self):
        r = DiffResult.from_dict(
            {
                "added": [
                    {
                        "conceptId": "H",
                        "categoryId": "level",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "removed": [
                    {
                        "conceptId": "L",
                        "categoryId": "level",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "common": [],
            }
        )
        assert len(r.added) == 1
        assert r.added[0].concept_id == "H"
        assert len(r.removed) == 1


class TestScanMatch:
    def test_from_dict(self):
        m = ScanMatch.from_dict(
            {
                "marking": "HIGH",
                "start": 0,
                "end": 4,
                "result": _validate_wire(rendered="HIGH"),
                "type": "standalone",
                "wrapped": False,
                "role": "whole",
            },
        )
        assert m.marking == "HIGH"
        assert type(m.result) is ValidateResult
        assert m.result.valid is True
        assert m.role == "whole"


class TestAccessModels:
    def test_access_rule_result(self):
        r = AccessRuleResult.from_dict(
            {
                "granted": True,
                "name": "Rule 1",
                "ruleIndex": 0,
                "skipped": False,
                "activation": {"matched": True, "assertions": [], "contextPaths": []},
                "comparisons": [],
                "rule": {
                    "artifact": {"kind": "access", "id": "a1", "version": "1.0.0"},
                    "ruleId": "r1",
                    "ruleDigest": "sha256:r1",
                },
            }
        )
        assert r.granted is True
        assert r.rule.rule_id == "r1"

    def test_access_rule_result_rejects_missing_qualified_rule(self):
        with pytest.raises(PydanticValidationError):
            AccessRuleResult.from_dict(
                {
                    "granted": True,
                    "name": "Rule 1",
                    "ruleIndex": 0,
                    "skipped": False,
                    "activation": {
                        "matched": True,
                        "assertions": [],
                        "contextPaths": [],
                    },
                    "comparisons": [],
                }
            )

    def test_access_decision(self):
        d = AccessDecision.from_dict({"granted": True, "rules": [], "warnings": []})
        assert d.granted is True
        assert d.rules == []


class TestGuideModels:
    def test_guide_rule_from_dict(self):
        r = GuideRule.from_dict(
            {
                "id": "r1",
                "name": "Rule 1",
                "keywords": ["foo"],
                "outcome": {"rendered": "HIGH"},
            }
        )
        assert r.id == "r1"
        assert r.keywords == ["foo"]

    def test_guide_rule_rejects_missing_required_shape(self):
        with pytest.raises(PydanticValidationError):
            GuideRule.from_dict({"id": "r1", "name": "Rule 1"})

    def test_guide_scan_span(self):
        s = GuideScanSpan.from_dict({"keyword": "name", "start": 5, "end": 9})
        assert s.keyword == "name"

    def test_guide_scan_result(self):
        r = GuideScanResult.from_dict(
            {
                "guideId": "pii-guide",
                "matchedKeywords": ["name"],
                "rule": {
                    "id": "pii-rule",
                    "name": "Contains PII",
                    "keywords": ["name"],
                    "outcome": {"rendered": "HIGH"},
                },
                "spans": [{"keyword": "name", "start": 0, "end": 4}],
            }
        )
        assert r.guide_id == "pii-guide"
        assert r.rule.id == "pii-rule"
        assert len(r.spans) == 1

    def test_guide_scan_result_must_name_its_guide(self):
        with pytest.raises(PydanticValidationError) as failure:
            GuideScanResult.from_dict(
                {
                    "matchedKeywords": [],
                    "rule": {
                        "id": "r1",
                        "name": "Rule",
                        "keywords": [],
                        "outcome": {"rendered": "HIGH"},
                    },
                    "spans": [],
                }
            )
        assert failure.value.errors()[0]["loc"] == ("guideId",)

    def test_evaluation_result(self):
        e = EvaluationResult.from_dict(
            {
                "guideId": "pii-guide",
                "aggregatedMarking": "HIGH",
                "selectedRules": [
                    {"id": "r1", "name": "R1", "keywords": [], "outcome": {}}
                ],
                "activeComputedRules": [],
                "effectiveMarkings": ["HIGH"],
                "breakdown": [],
                "contributingBreakdown": [],
            }
        )
        assert e.guide_id == "pii-guide"
        assert e.aggregated_marking == "HIGH"
