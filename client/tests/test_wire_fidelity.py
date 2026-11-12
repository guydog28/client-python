"""Wire-fidelity tests: every field of the 1.0 wire contract survives parsing.

Each test feeds a payload shaped like the 1.0 wire contract
(vendor/spec/json-schemas) and asserts the field is preserved on the parsed
model rather than dropped to a default. This guards against a model losing a
wire field silently as the spec evolves.
"""

import pytest
from pydantic import ValidationError

from ezclassify_rest_client import (
    CategoryView,
    ConceptView,
    FormatView,
    LabelPresetView,
    AccessRuleResult,
    AggregateResult,
    ArtifactReference,
    Assertion,
    Confidence,
    ContextSchemeScanResult,
    CoverageReport,
    EngineWarning,
    Fix,
    GuideDeterminationInput,
    ManualGuideSelectionInput,
    Term,
    DocumentAuditReport,
    EvaluationResult,
    GuideBreakdownEntry,
    GuideRule,
    Notice,
    ProcessResult,
    RuleReference,
    ScanMatch,
    SuggestResult,
    Suggestion,
    ValidateResult,
)

# What every reading of a marking answers, empty.
_NO_FINDINGS = {
    "assertions": [],
    "errors": [],
    "warnings": [],
    "appliedFixes": [],
    "notices": [],
}

# What every validate and process result carries beside the facts: the
# verdict on the text as written and the assessment of the one rendering.
_JUDGED = {
    **_NO_FINDINGS,
    "inputWasValid": True,
    "assessment": {
        "emitted": [],
        "omitted": [],
        "collapsed": [],
        "conflicts": [],
        "unrepresentable": [],
    },
}

# A process result adds the authoring answers.
_AUTHORED = {**_JUDGED, "renders": {}, "proposedFixes": []}


class TestSchemeResourceViews:
    """The views the scheme resource reads answer with decode the contract's members."""

    def test_citation_survives_a_concept_decode(self):
        concept = ConceptView.from_dict(
            {
                "id": "DATED",
                "name": "Dated",
                "views": {"default": "DATED"},
                "categories": ["date"],
                "parents": [],
                "position": 0,
                "aliases": [],
                "citation": "Source section 3",
            }
        )
        assert concept.citation == "Source section 3"

    def test_a_concept_carries_its_documentation_as_members(self):
        concept = ConceptView.from_dict(
            {
                "id": "H",
                "name": "High",
                "views": {"default": "H"},
                "categories": ["level"],
                "parents": [],
                "position": 1,
                "aliases": [],
                "definition": "The top level.",
                "guidance": "Use sparingly.",
                "notices": [
                    {
                        "conceptId": "H",
                        "conceptName": "High",
                        "type": "handling",
                        "text": "Handle with care.",
                        "required": True,
                    }
                ],
                "rulesReferencing": ["H needs STAFF."],
            }
        )
        assert concept.views == {"default": "H"}
        assert concept.definition == "The top level."
        assert concept.guidance == "Use sparingly."
        assert concept.rules_referencing == ["H needs STAFF."]

    def test_a_category_needs_only_its_identity_label_and_rollup(self):
        category = CategoryView.from_dict(
            {"id": "level", "label": "Level", "rollup": "max", "position": 2}
        )
        assert category.required is None
        assert category.single is None
        assert category.position == 2

    def test_a_format_decodes_with_its_layout(self):
        view = FormatView.from_dict(
            {
                "id": "banner",
                "surface": "marking",
                "mode": "inline",
                "categoryOrder": ["level"],
                "syntax": {"type": "text"},
            }
        )
        assert view.category_order == ["level"]
        assert view.mode == "inline"

    def test_a_label_preset_names_a_scope_it_belongs_to(self):
        preset = LabelPresetView.from_dict(
            {"id": "std", "label": "Standard", "scope": "marking"}
        )
        assert (preset.id, preset.scope) == ("std", "marking")


class TestAssertionWireFields:
    def test_replaced_concept_id_is_parsed(self):
        a = Assertion.from_dict(
            {
                "conceptId": "TK",
                "categoryId": "c",
                "confidence": "certain",
                "source": "parse",
                "replacedConceptId": "BYE",
            }
        )
        assert a.replaced_concept_id == "BYE"

    def test_replaced_concept_id_stays_none_when_absent(self):
        a = Assertion.from_dict(
            {
                "conceptId": "TK",
                "categoryId": "c",
                "confidence": "certain",
                "source": "parse",
            }
        )
        assert a.replaced_concept_id is None

    def test_confidence_is_typed_with_the_exported_enum(self):
        a = Assertion.from_dict(
            {
                "conceptId": "X",
                "categoryId": "c",
                "confidence": "inferred",
                "source": "infer",
            }
        )
        assert a.confidence is Confidence.inferred
        # Wire strings still compare equal (str-backed enum).
        assert a.confidence == "inferred"

    def test_a_decoded_assertion_without_confidence_is_refused(self):
        # The contract lists confidence as required with no default, so a
        # response that omits it is malformed. Reading it as "certain" would
        # give the assertion a trust level the server never sent.
        with pytest.raises(ValidationError) as failure:
            Assertion.from_dict(
                {"conceptId": "X", "categoryId": "c", "source": "parse"}
            )

        assert [(e["type"], e["loc"]) for e in failure.value.errors()] == [
            ("missing", ("confidence",))
        ]

    def test_a_decoded_assertion_with_null_confidence_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            Assertion.from_dict(
                {"conceptId": "X", "categoryId": "c", "confidence": None}
            )

        assert {e["loc"][0] for e in failure.value.errors()} == {"confidence"}

    def test_an_assertion_inside_a_response_without_confidence_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            CoverageReport.from_dict(
                {
                    "covered": False,
                    "missing": [{"categoryId": "level", "conceptId": "S"}],
                    "missingLabels": ["S"],
                    "excess": [],
                    "excessLabels": [],
                    "rendered": "LOW",
                }
            )

        assert failure.value.errors()[0]["loc"] == ("missing", 0, "confidence")

    def test_building_an_assertion_still_defaults_confidence_to_certain(self):
        # Negative control: the caller-side default is a construction
        # convenience and stays, only decoding requires the field.
        assert Assertion(category_id="level", concept_id="S").confidence is (
            Confidence.certain
        )


class TestProcessResultWireFields:
    _NOTICE = {
        "conceptId": "INT",
        "conceptName": "Internal Handling",
        "type": "handling",
        "text": "Handle under the internal program.",
        "required": True,
    }

    def test_recognition_renders_and_typed_values_are_preserved(self):
        assessment = {
            "emitted": [{"conceptId": "X", "categoryId": "c", "value": "A&B"}],
            "omitted": [],
            "collapsed": [],
            "conflicts": [],
            "unrepresentable": [],
        }
        r = ProcessResult.from_dict(
            {
                **_AUTHORED,
                "valid": True,
                "rendered": "M",
                "assessment": assessment,
                "notices": [],
                "renders": {
                    "marking/banner": {"rendered": "M", "assessment": assessment},
                    "marking/portion": {"rendered": "(M)", "assessment": assessment},
                },
                "recognition": {
                    "status": "complete",
                    "inputFormat": "marking/banner",
                    "role": "whole",
                    "surface": "marking",
                    "unmatched": [],
                    "corrections": [
                        {
                            "start": 0,
                            "end": 1,
                            "original": "m",
                            "replacement": "M",
                            "reason": "case",
                        }
                    ],
                },
            }
        )
        assert set(r.renders) == {"marking/banner", "marking/portion"}
        assert r.renders["marking/banner"]["assessment"] == assessment
        assert r.assessment == assessment
        assert r.recognition is not None
        assert r.recognition["inputFormat"] == "marking/banner"
        assert r.recognition["role"] == "whole"
        assert r.recognition["corrections"][0]["replacement"] == "M"
        assert r.renders["marking/banner"]["assessment"]["emitted"][0]["value"] == (
            "A&B"
        )

    def test_a_validate_result_carries_recognition_without_corrections(self):
        r = ValidateResult.from_dict(
            {
                **_JUDGED,
                "valid": True,
                "rendered": "M",
                "recognition": {
                    "status": "complete",
                    "inputFormat": "marking/portion",
                    "role": "part",
                    "surface": "marking",
                    "unmatched": [],
                },
            }
        )
        assert r.recognition == {
            "status": "complete",
            "inputFormat": "marking/portion",
            "role": "part",
            "surface": "marking",
            "unmatched": [],
        }

    def test_notices_are_parsed_into_the_exported_notice_model(self):
        r = ProcessResult.from_dict(
            {
                **_AUTHORED,
                "valid": True,
                "rendered": "M",
                "renders": {},
                "notices": [self._NOTICE],
            }
        )
        assert len(r.notices) == 1
        assert isinstance(r.notices[0], Notice)
        assert r.notices[0].concept_id == "INT"
        assert r.notices[0].required is True

    def test_a_result_without_notices_is_refused(self):
        # The contract answers with the field on every result, empty when the
        # marking carries none, so a result without it is malformed.
        payload = {**_AUTHORED, "valid": True, "rendered": "M"}
        del payload["notices"]
        with pytest.raises(ValidationError) as failure:
            ProcessResult.from_dict(payload)
        assert failure.value.errors()[0]["loc"] == ("notices",)

    def test_aggregate_carries_the_same_notices_field(self):
        r = AggregateResult.from_dict(
            {
                **_NO_FINDINGS,
                "valid": True,
                "rendered": "M",
                "proposedFixes": [],
                "notices": [self._NOTICE],
            }
        )
        assert len(r.notices) == 1
        assert r.notices[0].text == self._NOTICE["text"]


class TestScanMatchWireFields:
    @staticmethod
    def _match(**overrides):
        payload = {
            "marking": "(HIGH)",
            "start": 0,
            "end": 6,
            "result": {
                **_JUDGED,
                "valid": True,
                "assertions": [],
                "errors": [],
                "rendered": "HIGH",
                "notices": [],
            },
            "type": "embedded",
            "wrapped": True,
            "role": "part",
        }
        payload.update(overrides)
        return payload

    def test_inner_carries_the_unwrapped_marking(self):
        m = ScanMatch.from_dict(self._match(inner="HIGH"))
        # The wrapper shape is scheme-declared, so `inner` is the only supported
        # way back to the marking text; never strip delimiters off `marking`.
        assert m.inner == "HIGH"
        assert m.marking == "(HIGH)"

    def test_inner_stays_none_when_not_wrapped(self):
        m = ScanMatch.from_dict(
            self._match(marking="HIGH", end=4, type="standalone", wrapped=False)
        )
        assert m.inner is None


class TestSuggestionWireFields:
    def test_gated_requires_and_integer_order(self):
        s = Suggestion.from_dict(
            {
                "conceptId": "X",
                "categoryId": "c",
                "label": "X",
                "description": "d",
                "name": "n",
                "views": {"default": "X"},
                "group": "",
                "selected": False,
                "order": 2,
                "gated": True,
                "requires": ["REL_TO"],
            }
        )
        assert s.order == 2
        assert s.gated is True
        assert s.requires == ["REL_TO"]


class TestSuggestResultWireFields:
    def test_options_a_process_call_asked_for_are_typed_per_category(self):
        option = {
            "conceptId": "X",
            "categoryId": "c",
            "label": "X",
            "description": "d",
            "name": "n",
            "views": {"default": "X"},
            "group": "",
            "selected": True,
            "order": 0,
        }
        r = ProcessResult.from_dict(
            {
                **_AUTHORED,
                "valid": True,
                "rendered": "X",
                "renders": {},
                "suggestionsFor": {
                    "c": {
                        "suggestions": [option],
                        "warnings": [{"kind": "deprecation", "message": "w"}],
                    }
                },
            }
        )
        assert r.suggestions_for is not None
        assert isinstance(r.suggestions_for["c"], SuggestResult)
        assert r.suggestions_for["c"].suggestions[0].selected is True
        assert r.suggestions_for["c"].warnings[0].kind == "deprecation"


class TestAccessRuleResultWireFields:
    @staticmethod
    def _rule_result(**overrides):
        payload = {
            "ruleIndex": 0,
            "name": "compartment check",
            "granted": True,
            "skipped": False,
            "activation": {"matched": True, "assertions": [], "contextPaths": []},
            "comparisons": [],
            "rule": {
                "artifact": {"kind": "access", "id": "policy", "version": "1.0.0"},
                "ruleId": "r-1",
                "ruleDigest": "d-1",
            },
        }
        payload.update(overrides)
        return payload

    def test_modernized_from_is_parsed(self):
        r = AccessRuleResult.from_dict(
            self._rule_result(
                modernizedFrom=[
                    {
                        "conceptId": "TK",
                        "replacedConceptId": "BYE",
                        "conceptDisplay": "TK",
                        "replacedConceptDisplay": "BYE",
                    }
                ]
            )
        )
        # The substitution is what lets a "why" view report the verdict against
        # the marking the document actually carried, not just the current concept.
        assert r.modernized_from == [
            {
                "conceptId": "TK",
                "replacedConceptId": "BYE",
                "conceptDisplay": "TK",
                "replacedConceptDisplay": "BYE",
            }
        ]

    def test_modernized_from_stays_none_when_the_rule_was_not_modernized(self):
        r = AccessRuleResult.from_dict(self._rule_result())
        assert r.modernized_from is None


class TestGuideRuleWireFields:
    def test_full_rule_shape_is_parsed(self):
        r = GuideRule.from_dict(
            {
                "id": "r1",
                "name": "Rule 1",
                "keywords": ["kw"],
                "description": "why this rule exists",
                "category": "pii",
                "outcome": {"rendered": "HIGH", "concepts": [{"id": "LEVEL_HIGH"}]},
                "rationale": "policy 4.2",
                "when": {"any": ["A", "B"]},
                "overrides": ["r0"],
            }
        )
        assert r.description == "why this rule exists"
        assert r.category == "pii"
        assert r.outcome == {"rendered": "HIGH", "concepts": [{"id": "LEVEL_HIGH"}]}
        assert r.rationale == "policy 4.2"
        assert r.when == {"any": ["A", "B"]}
        assert r.overrides == ["r0"]

    def test_when_shorthand_forms(self):
        assert (
            GuideRule.from_dict(
                {"id": "a", "name": "a", "outcome": {}, "when": "X"}
            ).when
            == "X"
        )
        assert GuideRule.from_dict(
            {"id": "a", "name": "a", "outcome": {}, "when": ["X", "Y"]}
        ).when == [
            "X",
            "Y",
        ]


class TestEvaluationResultBreakdown:
    def test_breakdowns_are_parsed(self):
        entry = {
            "rule": {
                "artifact": {"kind": "guide", "id": "g1", "version": "1.0.0"},
                "ruleId": "r1",
                "ruleDigest": "sha256:r1",
            },
            "outcome": {"rendered": "HIGH"},
            "isComputed": True,
            "wasOverridden": True,
            "overriddenBy": {
                "artifact": {"kind": "guide", "id": "g1", "version": "1.0.0"},
                "ruleId": "r2",
                "ruleDigest": "sha256:r2",
            },
        }
        e = EvaluationResult.from_dict(
            {
                "guideId": "g1",
                "aggregatedMarking": "HIGH",
                "selectedRules": [],
                "activeComputedRules": [],
                "effectiveMarkings": ["HIGH"],
                "breakdown": [entry],
                "contributingBreakdown": [entry],
            }
        )
        assert len(e.breakdown) == 1
        b = e.breakdown[0]
        assert isinstance(b, GuideBreakdownEntry)
        assert b.rule.rule_id == "r1"
        assert b.outcome == {"rendered": "HIGH"}
        assert b.is_computed is True
        assert b.was_overridden is True
        assert b.overridden_by is not None and b.overridden_by.rule_id == "r2"
        assert len(e.contributing_breakdown) == 1


class TestDocumentAuditVocabulary:
    @staticmethod
    def _audit(vocabulary):
        return {
            "whole": None,
            "wholes": [],
            "wholeValidation": None,
            "parts": [],
            "wholeCoversParts": None,
            "unmarkedSpans": [],
            "proceduralFlags": [],
            "overallVerdict": "pass",
            "vocabulary": vocabulary,
            "documentDigest": "sha256:doc",
            "guideAssessment": None,
            "limitations": [],
            "markingRequirements": {"whole": False, "part": False},
        }

    def test_vocabulary_is_parsed(self):
        r = DocumentAuditReport.from_dict(
            self._audit(
                {
                    "whole": {"singular": "banner", "plural": "banners"},
                    "part": {"singular": "portion", "plural": "portions"},
                }
            )
        )
        assert isinstance(r.vocabulary["whole"], Term)
        assert r.vocabulary["whole"].singular == "banner"
        assert r.vocabulary["part"].plural == "portions"

    def test_null_vocabulary_stays_none(self):
        r = DocumentAuditReport.from_dict(self._audit(None))
        assert r.vocabulary is None


class TestUnknownResponseFields:
    """A response the server grows a field on must still decode here.

    Responses are open: a schema reachable from a response allows unknown
    fields, and new fields are optional. An SDK that refuses to decode one has
    turned an additive server change into a client outage, so this is the
    tolerance case for the Python packages.
    """

    _AUDIT = {
        "whole": None,
        "wholes": [],
        "wholeValidation": None,
        "parts": [],
        "wholeCoversParts": None,
        "unmarkedSpans": [],
        "proceduralFlags": [],
        "overallVerdict": "pass",
        "vocabulary": None,
        "documentDigest": "sha256:doc",
        "guideAssessment": None,
        "limitations": [],
        "markingRequirements": {"whole": False, "part": False},
    }

    def test_an_unknown_field_on_a_response_model_is_tolerated(self):
        decoded = DocumentAuditReport.from_dict(
            dict(self._AUDIT, fieldTheServerAddedLater={"anything": [1, 2, 3]})
        )

        assert decoded.overall_verdict == "pass"
        assert decoded.document_digest == "sha256:doc"

    def test_an_unknown_field_nested_in_a_response_is_tolerated(self):
        decoded = DocumentAuditReport.from_dict(
            dict(
                self._AUDIT,
                vocabulary={
                    "whole": {
                        "singular": "banner",
                        "plural": "banners",
                        "articleTheServerAddedLater": "the",
                    }
                },
            )
        )

        assert decoded.vocabulary["whole"].singular == "banner"

    def test_only_request_only_models_refuse_unknown_fields(self):
        # The generator closes a model everywhere only when its schema is
        # closed and the OpenAPI document uses it in a request body and never
        # in a response. A closed model that also comes back in responses, such
        # as Assertion, decodes openly and refuses unknown keywords only when a
        # caller constructs it; see TestConstructionClosedModels.
        import ezclassify_rest_client as contract
        from ezclassify_rest_client import models

        closed = sorted(
            name
            for name in contract.__all__
            if getattr(getattr(models, name, None), "model_config", {}).get("extra")
            == "forbid"
        )

        assert closed == [
            "GuideDeterminationInput",
            "GuideRuleSelection",
            "ManualGuideSelectionInput",
        ]

    def test_an_unknown_field_on_a_coverage_report_is_tolerated(self):
        # CoverageReport's JSON Schema is closed, but a response model must not
        # inherit that closure: a field a newer server adds is tolerated.
        decoded = CoverageReport.from_dict(
            {
                "covered": False,
                "missing": [],
                "missingLabels": [],
                "excess": [],
                "excessLabels": ["ALPHA"],
                "rendered": "LOW//ALPHA",
                "fieldTheServerAddedLater": True,
            }
        )

        assert decoded.excess_labels == ["ALPHA"]

    def test_an_unknown_field_nested_in_a_closed_schema_response_is_tolerated(self):
        decoded = Fix.from_dict(
            {
                "message": "Remove ALPHA.",
                "rendered": "LOW",
                "keeps": [],
                "adds": [],
                "removes": [
                    {
                        "conceptId": "ALPHA",
                        "categoryId": "share",
                        "hintTheServerAddedLater": "x",
                    }
                ],
                "fieldTheServerAddedLater": 1,
            }
        )

        assert decoded.removes[0].concept_id == "ALPHA"


class TestUnknownRequestFields:
    """Requests stay closed: a field the contract does not declare is refused."""

    _SELECTION = {
        "documentDigest": "sha256:doc",
        "rule": {
            "artifact": {"kind": "guide", "id": "g", "version": "1.0.0"},
            "ruleId": "r",
            "ruleDigest": "sha256:" + "0" * 64,
        },
        "evidence": [],
        "reason": "missed by scanning",
    }

    def test_a_declared_request_decodes(self):
        selection = ManualGuideSelectionInput.from_dict(self._SELECTION)

        assert selection.reason == "missed by scanning"

    def test_an_unknown_field_on_a_request_model_is_refused(self):
        with pytest.raises(ValidationError, match="extra"):
            ManualGuideSelectionInput.from_dict(
                dict(self._SELECTION, fieldTheCallerMistyped="x")
            )


class TestConstructionClosedModels:
    """A model callers build and servers return is strict only on construction."""

    def test_the_construction_closed_set_is_the_models_used_both_ways(self):
        import ezclassify_rest_client as contract
        from ezclassify_rest_client import _model_helpers, models

        closed_on_construction = sorted(
            name
            for name in contract.__all__
            if isinstance(getattr(models, name, None), type)
            and issubclass(getattr(models, name), _model_helpers._ClosedOnConstruction)
        )

        assert closed_on_construction == ["Assertion"]

    def test_a_mistyped_keyword_on_construction_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            Assertion(
                category_id="level",
                concept_id="S",
                expiresat="2027-01-01",  # the field is expires_at
            )

        assert failure.value.errors()[0]["type"] == "extra_forbidden"
        assert failure.value.errors()[0]["loc"] == ("expiresat",)

    def test_declared_keywords_and_wire_aliases_construct(self):
        by_name = Assertion(
            category_id="level", concept_id="S", replaced_concept_id="T"
        )
        by_alias = Assertion(categoryId="level", conceptId="S", replacedConceptId="T")

        assert by_name.replaced_concept_id == by_alias.replaced_concept_id == "T"

    def test_an_unknown_field_on_a_decoded_assertion_is_tolerated(self):
        decoded = Assertion.from_dict(
            {
                "categoryId": "level",
                "conceptId": "S",
                "confidence": "certain",
                "source": "parse",
                "hintTheServerAddedLater": 1,
            }
        )

        assert decoded.concept_id == "S"

    def test_an_unknown_field_on_an_assertion_inside_a_response_is_tolerated(self):
        decoded = CoverageReport.from_dict(
            {
                "covered": False,
                "missing": [
                    {
                        "categoryId": "level",
                        "conceptId": "S",
                        "confidence": "certain",
                        "source": "parse",
                        "hintTheServerAddedLater": 1,
                    }
                ],
                "missingLabels": ["S"],
                "excess": [],
                "excessLabels": [],
                "rendered": "LOW",
            }
        )

        assert decoded.missing[0].concept_id == "S"


class TestUnknownResponseEnumValues:
    """A response carrying an enum value this client predates must still decode.

    The contract is open-response and closed-request. A server that adds an
    enum value has made an additive change, so the model keeps the value as
    the string it received and every other field decodes as usual. Tests are
    grouped by where the enum sits: a field of the decoded model, an element
    of a list of models, a model nested inside another, and the discriminator
    of a source reference.
    """

    def test_an_unknown_value_in_a_top_level_field_is_kept(self):
        decoded = DocumentAuditReport.from_dict(
            dict(TestUnknownResponseFields._AUDIT, overallVerdict="needs-review")
        )

        assert decoded.overall_verdict == "needs-review"
        assert decoded.document_digest == "sha256:doc"

    def test_an_unknown_value_inside_list_elements_is_kept(self):
        decoded = ProcessResult.from_dict(
            {
                **_AUTHORED,
                "valid": False,
                "rendered": "M",
                "renders": {},
                "assertions": [
                    {
                        "conceptId": "S",
                        "categoryId": "level",
                        "confidence": "probable",
                        "source": "parse",
                    }
                ],
                "errors": [{"constraintId": "c1", "message": "m"}],
                "warnings": [{"kind": "advisory", "message": "w"}],
                "notices": [
                    dict(TestProcessResultWireFields._NOTICE, type="classified-by")
                ],
            }
        )

        assert decoded.assertions[0].confidence == "probable"
        assert decoded.errors[0].constraint_id == "c1"
        assert decoded.warnings[0].kind == "advisory"
        assert decoded.notices[0].type == "classified-by"
        assert decoded.notices[0].concept_id == "INT"

    def test_an_unknown_value_in_a_nested_model_is_kept(self):
        decoded = ContextSchemeScanResult.from_dict(
            {
                "resolution": {
                    "contextId": "ctx",
                    "resolvedVersion": "1.0.0",
                    "artifacts": [],
                },
                "result": {
                    "results": [],
                    "unread": [],
                    "limits": {
                        "status": "paused",
                        "limitHit": "memory",
                        "regionsFound": 0,
                    },
                },
            }
        )

        assert decoded.result.limits.status == "paused"
        assert decoded.result.limits.limit_hit == "memory"
        assert decoded.result.limits.regions_found == 0

    def test_an_unknown_artifact_kind_in_a_nested_reference_is_kept(self):
        decoded = RuleReference.from_dict(
            {
                "artifact": {"kind": "policy", "id": "p", "version": "1.0.0"},
                "ruleId": "r",
                "ruleDigest": "sha256:" + "0" * 64,
            }
        )

        assert decoded.artifact.kind == "policy"

    def test_a_decoded_unknown_value_serializes_back_unchanged(self):
        decoded = Assertion.from_dict(
            {
                "conceptId": "S",
                "categoryId": "level",
                "confidence": "probable",
                "source": "parse",
            }
        )

        wire = decoded.model_dump(mode="json", by_alias=True, exclude_none=True)

        assert wire["confidence"] == "probable"

    def test_known_values_keep_their_declared_types(self):
        # Negative control: opening the enum must not turn a known confidence
        # into a bare string or change a known literal.
        decoded = ProcessResult.from_dict(
            {
                **_AUTHORED,
                "valid": True,
                "rendered": "M",
                "renders": {},
                "assertions": [
                    {
                        "conceptId": "S",
                        "categoryId": "level",
                        "confidence": "inferred",
                        "source": "infer",
                    }
                ],
                "warnings": [{"kind": "rule", "message": "w"}],
            }
        )

        assert decoded.assertions[0].confidence is Confidence.inferred
        assert decoded.warnings[0].kind == "rule"
        assert Assertion(category_id="level", concept_id="S").confidence is (
            Confidence.certain
        )

    def test_a_value_of_the_wrong_type_is_still_refused(self):
        # Open means an unknown string, not any JSON value.
        with pytest.raises(ValidationError):
            EngineWarning.from_dict({"kind": 7, "message": "w"})


class TestUnknownRequestEnumValues:
    """Requests stay closed: an enum value the contract does not declare is refused.

    A model that only travels in requests refuses an unknown value however it
    is built. A model that travels both ways decodes openly and refuses the
    value only when a caller constructs it, which is how a request is built.
    """

    def test_a_request_only_model_refuses_an_unknown_value_when_decoded(self):
        with pytest.raises(ValidationError) as failure:
            ManualGuideSelectionInput.from_dict(
                dict(TestUnknownRequestFields._SELECTION, proposalOrigin="scraped")
            )

        assert failure.value.errors()[0]["type"] == "literal_error"
        assert failure.value.errors()[0]["loc"] == ("proposalOrigin",)

    def test_constructing_an_assertion_with_an_unknown_confidence_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            Assertion(category_id="level", concept_id="S", confidence="probable")

        assert failure.value.errors()[0]["loc"] == ("confidence",)

    def test_constructing_a_reference_with_an_unknown_kind_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            ArtifactReference(kind="policy", id="p", version="1.0.0")

        assert failure.value.errors()[0]["type"] == "literal_error"
        assert failure.value.errors()[0]["loc"] == ("kind",)

    def test_an_unknown_value_nested_in_a_constructed_request_is_refused(self):
        with pytest.raises(ValidationError) as failure:
            GuideDeterminationInput(
                findings=[
                    {
                        "findingId": "f1",
                        "documentDigest": "sha256:doc",
                        "decision": "deferred",
                        "reason": "r",
                    }
                ],
                manual_selections=[],
            )

        assert failure.value.errors()[0]["type"] == "literal_error"
        assert failure.value.errors()[0]["loc"] == ("findings", 0, "decision")

    def test_known_values_construct(self):
        # Negative control for the refusals above.
        determination = GuideDeterminationInput(
            findings=[
                {
                    "findingId": "f1",
                    "documentDigest": "sha256:doc",
                    "decision": "accepted",
                    "reason": "r",
                }
            ],
            manual_selections=[],
        )
        reference = ArtifactReference(kind="guide", id="g", version="1.0.0")

        assert determination.findings[0].decision == "accepted"
        assert reference.kind == "guide"
        assert (
            Assertion(
                category_id="level", concept_id="S", confidence=Confidence.inferred
            ).confidence
            is Confidence.inferred
        )
