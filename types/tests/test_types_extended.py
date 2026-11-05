"""from_dict wire-parsing tests for the remaining result models.

Covers EngineWarning, Fix, CoverageReport, ConceptDescription, FilterCount,
FilterResult, Notice, SuggestResult, RuleDescription, AccessRuleDescription,
AccessRequirementsDescription, StructuralViewCategory, StructuralView,
MarkingValidation, AuditWhole, UnmarkedSpan, AuditPart, and
DocumentAuditReport (the core engine results live in test_types.py), plus
the package version fallback when distribution metadata is unavailable.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import pytest
from pydantic import ValidationError

from unittest.mock import patch

import ezclassify_contract as _et
from ezclassify_contract.models import (
    AccessRequirementsDescription,
    AccessRuleDescription,
    AuditPart,
    AuditWhole,
    Change,
    CoverageReport,
    ConceptDescription,
    DocumentAuditReport,
    FilterCount,
    FilterResult,
    Fix,
    MarkingValidation,
    Notice,
    RuleDescription,
    StructuralView,
    StructuralViewCategory,
    SuggestResult,
    UnmarkedSpan,
    EngineWarning,
)

_RECOGNITION = {"status": "complete", "surface": "marking", "unmatched": []}


def _validation(**overrides: object) -> dict:
    """A complete MarkingValidation payload, as an audit sends one."""
    validation: dict = {
        "assertions": [],
        "recognition": _RECOGNITION,
        "valid": True,
        "inputWasValid": True,
        "errors": [],
        "proposedFixes": [],
        "appliedFixes": [],
        "rendered": "HIGH",
    }
    validation.update(overrides)
    return validation


class TestWarningFromDict:
    def test_minimal(self):
        w = EngineWarning.from_dict({"kind": "deprecation", "message": "use X instead"})
        assert w.kind == "deprecation"
        assert w.message == "use X instead"
        assert w.concept_id is None
        assert w.replacement is None

    def test_full(self):
        w = EngineWarning.from_dict(
            {
                "kind": "rule",
                "message": "flagged",
                "conceptId": "C1",
                "categoryId": "level",
                "ruleId": "r1",
                "replacement": "C2",
            }
        )
        assert w.concept_id == "C1"
        assert w.replacement == "C2"


class TestFixFromDict:
    def test_keeps_adds_and_removes_round_trip(self):
        wire = {
            "message": "Replace OLD with NEW, keep the rest",
            "rendered": "H//NEW//A",
            "keeps": [
                {"conceptId": "H", "categoryId": "level"},
                {"conceptId": "A", "categoryId": "audience"},
            ],
            "adds": [{"conceptId": "NEW", "categoryId": "control"}],
            "removes": [{"conceptId": "OLD", "categoryId": "control"}],
        }
        f = Fix.from_dict(wire)
        assert f.message == "Replace OLD with NEW, keep the rest"
        assert f.rendered == "H//NEW//A"
        assert [(c.concept_id, c.category_id) for c in f.keeps] == [
            ("H", "level"),
            ("A", "audience"),
        ]
        assert [(c.concept_id, c.category_id) for c in f.adds] == [("NEW", "control")]
        assert [(c.concept_id, c.category_id) for c in f.removes] == [
            ("OLD", "control")
        ]
        assert f.model_dump(by_alias=True, exclude_none=True) == wire


class TestChangeFromDict:
    def test_add_action(self):
        c = Change.from_dict(
            {
                "ruleId": "r1",
                "action": "add",
                "add": [{"conceptId": "NEW", "categoryId": "control"}],
                "message": "added NEW",
            }
        )
        assert c.rule_id == "r1"
        assert c.action == "add"
        assert [(x.concept_id, x.category_id) for x in c.add] == [("NEW", "control")]
        assert c.remove is None
        assert c.trigger_concept_ids is None

    def test_remove_action(self):
        c = Change.from_dict(
            {
                "ruleId": "r2",
                "action": "remove",
                "remove": [{"conceptId": "OLD", "categoryId": "control"}],
                "message": "removed OLD",
                "triggerConceptIds": ["T1"],
            }
        )
        assert c.action == "remove"
        assert c.add is None
        assert [(x.concept_id, x.category_id) for x in c.remove] == [("OLD", "control")]
        assert c.trigger_concept_ids == ["T1"]

    def test_replace_action(self):
        c = Change.from_dict(
            {
                "ruleId": "r3",
                "action": "replace",
                "add": [{"conceptId": "NEW", "categoryId": "control"}],
                "remove": [{"conceptId": "OLD", "categoryId": "control"}],
                "message": "swapped OLD for NEW",
            }
        )
        assert c.action == "replace"
        assert [(x.concept_id, x.category_id) for x in c.add] == [("NEW", "control")]
        assert [(x.concept_id, x.category_id) for x in c.remove] == [("OLD", "control")]

    def test_reorder_action(self):
        c = Change.from_dict(
            {
                "ruleId": "r4",
                "action": "reorder",
                "message": "canonicalized via a tolerant rule",
            }
        )
        assert c.action == "reorder"
        assert c.add is None
        assert c.remove is None


class TestCoverageReportFromDict:
    def test_rejects_missing_required_missing_list(self):
        with pytest.raises(ValidationError):
            CoverageReport.from_dict(
                {
                    "covered": False,
                    "missingLabels": [],
                    "excess": [],
                    "excessLabels": [],
                    "rendered": "",
                }
            )

    def test_with_missing_assertions(self):
        r = CoverageReport.from_dict(
            {
                "covered": False,
                "missing": [
                    {
                        "conceptId": "A",
                        "categoryId": "level",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "missingLabels": ["A-label"],
                "excess": [],
                "excessLabels": [],
                "rendered": "X",
            }
        )
        assert len(r.missing) == 1
        assert r.missing[0].concept_id == "A"
        assert r.missing_labels == ["A-label"]
        assert r.excess == []

    def test_rejects_missing_required_excess_list(self):
        with pytest.raises(ValidationError):
            CoverageReport.from_dict(
                {
                    "covered": True,
                    "missing": [],
                    "missingLabels": [],
                    "excessLabels": [],
                    "rendered": "",
                }
            )

    def test_with_excess_assertions(self):
        r = CoverageReport.from_dict(
            {
                "covered": False,
                "missing": [],
                "missingLabels": [],
                "excess": [
                    {
                        "conceptId": "ALPHA",
                        "categoryId": "share",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                "excessLabels": ["ALPHA"],
                "rendered": "LOW//ALPHA",
            }
        )
        assert r.covered is False
        assert r.missing == []
        assert [a.concept_id for a in r.excess] == ["ALPHA"]
        assert r.excess_labels == ["ALPHA"]

    def test_covered_true(self):
        r = CoverageReport.from_dict(
            {
                "covered": True,
                "missing": [],
                "missingLabels": [],
                "excess": [],
                "excessLabels": [],
                "rendered": "",
            }
        )
        assert r.covered is True


class TestConceptDescriptionFromDict:
    def test_required_fields(self):
        c = ConceptDescription.from_dict(
            {"conceptId": "H", "categoryId": "level", "name": "High", "lines": []}
        )
        assert c.concept_id == "H"
        assert c.category_id == "level"
        assert c.rules is None

    def test_with_rules(self):
        c = ConceptDescription.from_dict(
            {
                "conceptId": "H",
                "categoryId": "level",
                "name": "High",
                "lines": ["Line 1"],
                "definition": "def",
                "guidance": "guide",
                "rules": ["r1", "r2"],
            }
        )
        assert c.rules == ["r1", "r2"]
        assert c.lines == ["Line 1"]
        assert c.definition == "def"


class TestFilterCountFromDict:
    def test_basic(self):
        fc = FilterCount.from_dict({"visible": 3, "total": 10})
        assert fc.visible == 3
        assert fc.total == 10

    def test_rejects_missing_counts(self):
        with pytest.raises(ValidationError):
            FilterCount.from_dict({})


class TestFilterResultFromDict:
    def test_empty(self):
        fr = FilterResult.from_dict(
            {
                "visibleIds": [],
                "categoryCounts": {},
                "total": {"visible": 0, "total": 0},
            }
        )
        assert fr.visible_ids == []
        assert fr.category_counts == {}
        assert fr.total.visible == 0

    def test_with_category_counts(self):
        fr = FilterResult.from_dict(
            {
                "visibleIds": ["id1", "id2"],
                "categoryCounts": {
                    "level": {"visible": 2, "total": 5},
                    "sci": {"visible": 0, "total": 3},
                },
                "total": {"visible": 2, "total": 8},
            }
        )
        assert "level" in fr.category_counts
        assert fr.category_counts["level"].visible == 2
        assert fr.total.total == 8
        assert fr.visible_ids == ["id1", "id2"]

    def test_rejects_null_category_counts(self):
        with pytest.raises(ValidationError):
            FilterResult.from_dict(
                {
                    "visibleIds": [],
                    "categoryCounts": None,
                    "total": {"visible": 0, "total": 0},
                }
            )


class TestNoticeFromDict:
    def test_basic(self):
        n = Notice.from_dict(
            {
                "conceptId": "C1",
                "conceptName": "Concept One",
                "type": "handling",
                "text": "Handle with care",
                "required": True,
            }
        )
        assert n.concept_id == "C1"
        assert n.concept_name == "Concept One"
        assert n.required is True

    def test_rejects_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Notice.from_dict({})


class TestSuggestResultFromDict:
    def test_empty(self):
        sr = SuggestResult.from_dict({"suggestions": [], "warnings": []})
        assert sr.suggestions == []
        assert sr.warnings == []

    def test_carries_options_and_nothing_about_the_marking(self):
        # Suggest answers what a picker may offer. Whether the marking reads
        # and stands is what validate and process answer, so members a server
        # sends beyond the suggest contract do not appear on the result.
        sr = SuggestResult.from_dict(
            {
                "suggestions": [],
                "warnings": [],
                "currentRendered": "PREV",
                "currentValid": True,
            }
        )
        assert set(SuggestResult.model_fields) == {"suggestions", "warnings"}
        assert not hasattr(sr, "current_rendered")

    def test_with_suggestions(self):
        sr = SuggestResult.from_dict(
            {
                "suggestions": [
                    {
                        "conceptId": "H",
                        "categoryId": "level",
                        "label": "HIGH",
                        "description": "High level",
                        "name": "High",
                        "views": {"default": "HIGH"},
                        "group": "",
                        "selected": False,
                        "order": 0,
                    }
                ],
                "warnings": [{"kind": "deprecation", "message": "msg"}],
            }
        )
        assert len(sr.suggestions) == 1
        assert sr.suggestions[0].concept_id == "H"
        assert len(sr.warnings) == 1


class TestRuleDescriptionFromDict:
    def test_minimal(self):
        with pytest.raises(ValidationError):
            RuleDescription.from_dict({"ruleId": "r1", "guideId": "g1"})

    def test_full(self):
        r = RuleDescription.from_dict(
            {
                "rule": {
                    "artifact": {"kind": "guide", "id": "g2", "version": "1"},
                    "ruleId": "r2",
                    "ruleDigest": "sha256:r2",
                },
                "guide": {"kind": "guide", "id": "g2", "version": "1"},
                "name": "Rule Two",
                "outcomeText": "outcome",
                "isComputed": True,
                "dependsOn": [],
                "overrides": [],
                "lines": ["line1"],
                "description": "desc",
                "whenText": "when X",
            }
        )
        assert r.is_computed is True
        assert r.rule.rule_id == "r2"
        assert r.guide.id == "g2"
        assert r.description == "desc"
        assert r.when_text == "when X"


class TestAccessRuleDescriptionFromDict:
    def test_minimal(self):
        with pytest.raises(ValidationError):
            AccessRuleDescription.from_dict({"ruleId": "ar1"})

    def test_full(self):
        r = AccessRuleDescription.from_dict(
            {
                "rule": {
                    "artifact": {"kind": "access", "id": "acc1", "version": "1"},
                    "ruleId": "ar2",
                    "ruleDigest": "sha256:ar2",
                },
                "access": {"kind": "access", "id": "acc1", "version": "1"},
                "scheme": {
                    "kind": "scheme",
                    "id": "cedar-valley-protection",
                    "version": "1",
                },
                "name": "Clearance Required",
                "requirementText": "HIGH/CA required",
                "attributesNeeded": ["HIGH", "CA"],
                "dependsOn": [],
                "overrides": [],
                "lines": ["clearance_level >= HIGH"],
                "description": "desc",
                "whenText": "when level = HIGH",
            }
        )
        assert r.access.id == "acc1"
        assert r.attributes_needed == ["HIGH", "CA"]
        assert r.when_text == "when level = HIGH"


class TestAccessRequirementsDescriptionFromDict:
    def test_empty(self):
        with pytest.raises(ValidationError):
            AccessRequirementsDescription.from_dict({})

    def test_with_rules(self):
        r = AccessRequirementsDescription.from_dict(
            {
                "marking": "HIGH/CA",
                "assertions": [],
                "access": {"kind": "access", "id": "acc1", "version": "1"},
                "scheme": {
                    "kind": "scheme",
                    "id": "cedar-valley-protection",
                    "version": "1",
                },
                "appliedRules": [
                    {
                        "artifact": {"kind": "access", "id": "acc1", "version": "1"},
                        "ruleId": "ar1",
                        "ruleDigest": "sha256:ar1",
                    }
                ],
                "rules": [],
                "combinedRequirementText": "HIGH/CA",
                "combinedAttributesNeeded": ["HIGH", "CA"],
                "assertionDisplays": [],
                "lines": ["l1"],
            }
        )
        assert r.marking == "HIGH/CA"
        assert r.applied_rules[0].rule_id == "ar1"
        assert r.combined_attributes_needed == ["HIGH", "CA"]


class TestStructuralViewCategoryFromDict:
    def test_basic(self):
        c = StructuralViewCategory.from_dict(
            {
                "id": "level",
                "label": "Classification Level",
                "items": [{"id": "H", "name": "High"}],
            }
        )
        assert c.id == "level"
        assert c.label == "Classification Level"
        assert len(c.items) == 1

    def test_rejects_missing_required_fields(self):
        with pytest.raises(ValidationError):
            StructuralViewCategory.from_dict({})


class TestStructuralViewFromDict:
    def test_rejects_missing_required_fields(self):
        with pytest.raises(ValidationError):
            StructuralView.from_dict({})

    def test_with_categories(self):
        v = StructuralView.from_dict(
            {
                "id": "tiers-view",
                "name": "Tiers",
                "description": "Tiers structural view",
                "categories": [{"id": "level", "label": "Level", "items": []}],
                "uncategorized": [
                    {
                        "id": "misc",
                        "name": "Misc",
                        "views": {"default": "MISC"},
                        "aliases": [],
                        "categories": [],
                        "parents": [],
                        "position": 0,
                    }
                ],
                "vocabulary": {"concept": {"singular": "item", "plural": "items"}},
            }
        )
        assert v.id == "tiers-view"
        assert len(v.categories) == 1
        assert v.categories[0].id == "level"
        assert len(v.uncategorized) == 1
        assert v.vocabulary["concept"].singular == "item"
        assert v.vocabulary["concept"].plural == "items"


class TestMarkingValidationFromDict:
    def test_valid(self):
        mv = MarkingValidation.from_dict(
            _validation(
                assertions=[
                    {
                        "categoryId": "level",
                        "conceptId": "HIGH",
                        "confidence": "certain",
                        "source": "parse",
                    }
                ],
                recognition=dict(_RECOGNITION, inputFormat="marking/long", role="part"),
            )
        )
        assert mv.valid is True
        assert mv.input_was_valid is True
        assert mv.rendered == "HIGH"
        assert mv.errors == []
        assert mv.assertions[0].concept_id == "HIGH"
        assert mv.recognition["inputFormat"] == "marking/long"
        assert mv.recognition["role"] == "part"

    def test_settled_and_as_written_are_separate_verdicts(self):
        mv = MarkingValidation.from_dict(_validation(valid=True, inputWasValid=False))
        assert mv.valid is True
        assert mv.input_was_valid is False

    def test_invalid_with_errors(self):
        mv = MarkingValidation.from_dict(
            _validation(
                valid=False,
                inputWasValid=False,
                errors=[{"constraintId": "c1", "message": "err"}],
                proposedFixes=[
                    {
                        "message": "fix",
                        "rendered": "HIGH//C",
                        "keeps": [],
                        "adds": [{"conceptId": "C", "categoryId": "cat"}],
                        "removes": [],
                    }
                ],
                rendered="",
            )
        )
        assert mv.valid is False
        assert len(mv.errors) == 1
        assert len(mv.proposed_fixes) == 1
        # proposedFixes parse into typed Fix models, matching the sibling
        # result models (ProcessResult, AggregateResult, SuggestResult).
        assert isinstance(mv.proposed_fixes[0], Fix)
        assert mv.proposed_fixes[0].adds[0].concept_id == "C"

    @pytest.mark.parametrize(
        "member", ["assertions", "recognition", "inputWasValid", "appliedFixes"]
    )
    def test_members_the_audit_always_sends_are_required(self, member):
        payload = _validation()
        del payload[member]
        with pytest.raises(ValidationError):
            MarkingValidation.from_dict(payload)

    def test_applied_fixes_with_a_reorder_change(self):
        mv = MarkingValidation.from_dict(
            _validation(
                appliedFixes=[
                    {
                        "ruleId": "r1",
                        "action": "reorder",
                        "message": "canonicalized via a tolerant rule",
                    }
                ]
            )
        )
        assert len(mv.applied_fixes) == 1
        change = mv.applied_fixes[0]
        assert isinstance(change, Change)
        assert change.rule_id == "r1"
        assert change.action == "reorder"
        assert change.message == "canonicalized via a tolerant rule"
        assert change.add is None
        assert change.remove is None


class TestAuditWholeFromDict:
    def test_basic(self):
        w = AuditWhole.from_dict(
            {
                "marking": "HIGH/CA",
                "start": 0,
                "end": 7,
                "offsetEncoding": "utf-8-bytes",
            }
        )
        assert w.marking == "HIGH/CA"
        assert w.start == 0
        assert w.end == 7

    def test_defaults(self):
        with pytest.raises(ValidationError):
            AuditWhole.from_dict({})

    def test_rejects_fractional_offsets(self):
        with pytest.raises(ValidationError):
            AuditWhole.from_dict(
                {
                    "marking": "HIGH",
                    "start": 0.5,
                    "end": 4,
                    "offsetEncoding": "utf-8-bytes",
                }
            )


class TestUnmarkedSpanFromDict:
    def test_basic(self):
        s = UnmarkedSpan.from_dict(
            {
                "start": 10,
                "end": 20,
                "text": "some text",
                "offsetEncoding": "utf-8-bytes",
            }
        )
        assert s.start == 10
        assert s.end == 20
        assert s.text == "some text"

    def test_defaults(self):
        with pytest.raises(ValidationError):
            UnmarkedSpan.from_dict({})


class TestAuditPartFromDict:
    def test_without_coverage_or_validation(self):
        with pytest.raises(ValidationError):
            AuditPart.from_dict({"marking": "HIGH", "start": 0, "end": 10})

    def test_with_coverage_and_validation(self):
        p = AuditPart.from_dict(
            {
                "marking": "HIGH/CA",
                "text": "Restricted",
                "start": 0,
                "end": 10,
                "offsetEncoding": "utf-8-bytes",
                "scopeId": "part:1",
                "validation": _validation(rendered="HIGH/CA"),
            }
        )
        assert p.validation.valid is True
        assert p.scope_id == "part:1"

    def test_rejects_fractional_offsets(self):
        with pytest.raises(ValidationError):
            AuditPart.from_dict(
                {
                    "marking": "HIGH",
                    "start": 0,
                    "end": 4.5,
                    "offsetEncoding": "utf-8-bytes",
                    "scopeId": "part:1",
                    "validation": {
                        "valid": True,
                        "errors": [],
                        "proposedFixes": [],
                        "rendered": "HIGH",
                    },
                }
            )


class TestDocumentAuditReportFromDict:
    def test_empty(self):
        with pytest.raises(ValidationError):
            DocumentAuditReport.from_dict({})

    def test_with_optional_coverage_fields(self):
        coverage_dict = {
            "covered": True,
            "missing": [],
            "missingLabels": [],
            "excess": [],
            "excessLabels": [],
            "rendered": "HIGH",
        }
        r = DocumentAuditReport.from_dict(
            {
                "whole": "HIGH/CA",
                "wholes": [
                    {
                        "marking": "HIGH/CA",
                        "start": 0,
                        "end": 7,
                        "offsetEncoding": "utf-8-bytes",
                    }
                ],
                "wholeValidation": _validation(rendered="HIGH/CA"),
                "parts": [
                    {
                        "marking": "HIGH",
                        "text": "Restricted",
                        "start": 0,
                        "end": 10,
                        "offsetEncoding": "utf-8-bytes",
                        "scopeId": "part:1",
                        "validation": _validation(),
                    }
                ],
                "wholeCoversParts": coverage_dict,
                "unmarkedSpans": [
                    {
                        "start": 10,
                        "end": 20,
                        "text": " and more text",
                        "offsetEncoding": "utf-8-bytes",
                    }
                ],
                "proceduralFlags": ["flag1"],
                "overallVerdict": "pass",
                "vocabulary": None,
                "documentDigest": "sha256:doc",
                "guideAssessment": None,
                "limitations": [],
                "markingRequirements": {"whole": False, "part": False},
            }
        )
        assert r.whole == "HIGH/CA"
        assert len(r.wholes) == 1
        assert r.whole_validation is not None
        assert r.whole_validation.valid is True
        assert r.whole_covers_parts is not None
        assert r.whole_covers_parts.covered is True
        assert len(r.unmarked_spans) == 1
        assert r.procedural_flags == ["flag1"]
        assert r.overall_verdict == "pass"


class TestVersionFallback:
    """__version__ falls back to the literal when distribution metadata is absent."""

    def test_package_not_found_falls_back_to_literal(self):
        original = _et.__version__
        try:
            with patch(
                "importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError(
                    "ezclassify-contract"
                ),
            ):
                importlib.reload(_et)
                assert _et.__version__ == "1.0.0.dev0"
        finally:
            importlib.reload(_et)
        assert _et.__version__ == original


def _component(component_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": component_id,
        "version": "latest",
        "resolvedVersion": "1.2.0",
        **extra,
    }


class TestContextDescription:
    """The Context description keeps declared and resolved versions apart."""

    def _body(self, **extra: object) -> dict[str, object]:
        return {
            "id": "ctx",
            "version": "1.2.0",
            "scheme": _component("levels"),
            "schemes": [
                {
                    "selector": "levels",
                    "id": "levels",
                    "version": "1.2.0",
                    "roles": ["primary", "crosswalk-source"],
                }
            ],
            **extra,
        }

    def test_reads_every_component_with_both_versions(self):
        description = _et.ContextDescription.from_dict(
            self._body(
                guides=[_component("handling")],
                access=_component("clearance"),
                crosswalks=[_component("levels-to-legacy")],
            )
        )
        assert description.scheme.version == "latest"
        assert description.scheme.resolved_version == "1.2.0"
        assert [g.id for g in description.guides] == ["handling"]
        assert description.access is not None
        assert description.crosswalks[0].resolved_version == "1.2.0"
        assert description.schemes[0].roles == ["primary", "crosswalk-source"]

    def test_an_omitted_collection_is_empty_and_layers_come_from_the_scheme(self):
        bare = _et.ContextDescription.from_dict(self._body())
        assert bare.guides == [] and bare.crosswalks == []
        assert bare.access is None and bare.layers == []
        layered = _et.ContextDescription.from_dict(
            self._body(scheme=_component("levels", layers=[_component("overlay")]))
        )
        assert [layer.id for layer in layered.layers] == ["overlay"]

    def test_a_component_without_its_resolved_version_is_refused(self):
        with pytest.raises(ValidationError):
            _et.ContextDescription.from_dict(
                self._body(scheme={"id": "levels", "version": "latest"})
            )


def test_a_scheme_scope_has_an_id_and_a_label():
    scope = _et.SchemeScope.from_dict({"id": "doc", "label": "Document"})
    assert (scope.id, scope.label) == ("doc", "Document")
    with pytest.raises(ValidationError):
        _et.SchemeScope.from_dict({"id": "doc"})
