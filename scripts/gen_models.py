#!/usr/bin/env python3
"""Generate the shipped Pydantic wire models from vendored contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import pprint
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "types/ezclassify_contract/models.py"

# Column limit for generated docstrings. models.py is excluded from
# `ruff format` (see the root pyproject) because regen freshness requires it to
# match this generator byte for byte, so wrapping happens here, at the width
# the formatter uses for the rest of the tree.
DOCSTRING_WIDTH = 88

# The generated models, in a deliberate order: it keeps the generated output
# readable and the long-established package surface stable.  Where each name's
# schema comes from is decided further down, under "Schema sources".  A name
# with a leading underscore is a body the client decodes but no public method
# returns, so it is generated strictly like the rest and kept off the public
# surface.
MODEL_ORDER = [
    "Confidence",
    "Attribution",
    "ArtifactReference",
    "SourceReference",
    "RuleSourceReference",
    "RuleReference",
    "AssertionReference",
    "AccessOperand",
    "AccessComparisonResult",
    "AccessRuleActivation",
    "Assertion",
    "ValidationError",
    "EngineWarning",
    "FixConceptReference",
    "Fix",
    "Change",
    "ConceptColor",
    "ValidateResult",
    "ProcessResult",
    "TraceEntry",
    "TraceRepair",
    "TraceValidationIssue",
    "TraceInference",
    "ExplanationTrace",
    "Suggestion",
    "AggregateResult",
    "DiffResult",
    "ScanMatch",
    "ScanLimits",
    "ScanResponseBody",
    "AccessRuleResult",
    "AccessDecision",
    "GuideRule",
    "GuideScanSpan",
    "GuideScanResult",
    "GuideBreakdownEntry",
    "EvaluationResult",
    "CoverageReport",
    "ConceptDescription",
    "FilterCount",
    "FilterResult",
    "Notice",
    "SuggestResult",
    "RuleDescription",
    "AccessRuleDescription",
    "AccessRequirementsDescription",
    "ConceptView",
    "StructuralViewCategory",
    "StructuralView",
    "MarkingValidation",
    "AuditWhole",
    "UnmarkedSpan",
    "AuditPart",
    "Term",
    "ReferenceSurfaceLabel",
    "MarkingColorRule",
    "SchemeSummary",
    "CategoryView",
    "FormatView",
    "SchemeGrammar",
    "LabelPresetView",
    "SchemeScope",
    "DocumentAuditReport",
    "ContextResolution",
    "AssessmentLimitation",
    "ContentEvidenceSpan",
    "GuideNomination",
    "GuideFindingDetermination",
    "ManualGuideSelectionInput",
    "ManualGuideSelection",
    "GuideDeterminationInput",
    "GuideFactReference",
    "AssertionSupport",
    "GuideCompiledDetail",
    "GuideCompiledResult",
    "GuideUnitEvaluation",
    "GuideContentEvaluation",
    "GuideScopeCoverage",
    "DocumentGuideAssessment",
    "DocumentResponseCounts",
    "DocumentResponseProjection",
    "RenderResponse",
    "NormalizeResponse",
    "ContextSchemeProcessResult",
    "ContextSchemeValidateResult",
    "ContextSchemeExplainResult",
    "ContextSchemeSuggestResult",
    "ContextSchemeSuggestForCategoriesResult",
    "ContextSchemeAggregateResult",
    "ContextSchemeScanResult",
    "ContextSchemeRenderResult",
    "ContextSchemeNormalizeResult",
    "ContextSchemeCoverageResult",
    "ContextSchemeConceptDescriptionResult",
    "ContextSchemeDiffResult",
    "ContextSchemeFilterConceptsResult",
    "ContextSchemeNoticesResult",
    "ContextSchemeViewResult",
    "ContextGuideScanResult",
    "ContextGuideEvaluationResult",
    "ContextGuideFilterRulesResult",
    "ContextGuideRuleDescriptionResult",
    "ContextGuideViewResult",
    "ContextAccessDecisionResult",
    "ContextAccessRequirementsResult",
    "ContextAccessRuleDescriptionResult",
    "CtxAccessRulesResponseBody",
    "_HealthResponse",
    "_CtxListResponseBody",
    "_CtxVersionsResponseBody",
    "ContextComponent",
    "ContextSchemeDescriptor",
    "ContextDescription",
    "ContextCrosswalkTranslationResult",
    "ContextDocumentAuditResult",
]

JSON_TOP = {
    "Assertion": "assertion",
    "ValidationError": "validation-error",
    "EngineWarning": "warning",
    "Fix": "fix",
    "Change": "change",
    "ValidateResult": "validate-result",
    "ProcessResult": "process-result",
    "ExplanationTrace": "explanation-trace",
    "Suggestion": "suggestion",
    "AggregateResult": "aggregate-result",
    "DiffResult": "diff-result",
    "ScanMatch": "scan-result",
    "AccessRuleResult": "access-rule-result",
    "AccessDecision": "access-decision",
    "GuideScanSpan": "guide-scan-span",
    "GuideScanResult": "guide-scan-result",
    "EvaluationResult": "evaluation-result",
    "SuggestResult": "suggest-result",
}

REF_RENAMES = {
    "Warning": "EngineWarning",
    # The canonical JSON Schemas call the collected-notice shape
    # CollectedNotice; the OpenAPI component this package publishes it from is
    # Notice. Same schema, two spellings, so the results that carry a notice
    # list resolve to the exported model instead of an opaque dictionary.
    "CollectedNotice": "Notice",
    "ScanResult": "ScanMatch",
    "CheckCoverageResult": "CoverageReport",
    "DocumentUnmarkedSpan": "UnmarkedSpan",
    "SchemeViewResponse": "StructuralView",
    "GuideViewResponse": "StructuralView",
    "CtxComponentDescriptor": "ContextComponent",
    "CtxDescribeResponseBody": "ContextDescription",
}

BASE_MIXINS = {
    "SourceReference": "_SourceIdentityMixin",
    "RuleSourceReference": "_SourceIdentityMixin",
    "ContextDescription": "_ContextDescriptionMixin",
}

# Public models declared as a subclass of another public model, because the
# contract defines them that way: a process result is a validate result with
# the authoring answers added. The subclass declares only the fields its base
# does not, so a ProcessResult goes wherever a ValidateResult is expected.
# Every field the two share has to come out of the generator exactly as it
# does on the base, or the subclass would quietly narrow or widen it;
# `Generator.inheritance_conflicts` checks that before anything is rendered.
BASE_MODELS = {
    "ProcessResult": "ValidateResult",
}

DEFAULTS: dict[tuple[str, str], str] = {
    ("Assertion", "confidence"): "Confidence.certain",
    ("Assertion", "source"): '"parse"',
    ("GuideRule", "keywords"): "factory",
    # The wire omits a collection the Context does not declare. "No guide" and
    # "no crosswalk" are answers callers act on, so they decode as empty.
    ("ContextDescription", "guides"): "factory",
    ("ContextDescription", "crosswalks"): "factory",
}

# Models callers build with keywords to put in a request, closed on
# construction whatever their canonical schema says. The contract publishes
# its result schemas open, so a response may gain fields, and a model read
# from responses inherits that. A request is closed, though, and an undeclared
# keyword passed while building one is a caller's typo that would otherwise
# vanish before the request is sent. `Generator.closure` applies this table.
CLOSED_ON_CONSTRUCTION = {"Assertion"}

# ---------------------------------------------------------------------------
# Schema sources.
#
# Most public models are generated from an OpenAPI component of the same name,
# which needs no configuration.  Four tables hold the complete set of
# exceptions — JSON_TOP above, plus the three below — and they are the only
# places a source is ever named by hand.  A public model with no same-named
# component and no entry in one of them cannot be generated; `Generator.source`
# says exactly that and names the tables.
# ---------------------------------------------------------------------------

# Anonymous canonical objects that have established public Python names.  The
# value is (document kind, root schema name, property path within it).
INLINE_SOURCES = {
    "Confidence": ("json", "assertion", ("properties", "confidence")),
    "FilterCount": ("openapi", "FilterResult", ("properties", "total")),
    "AuditWhole": ("openapi", "DocumentAuditReport", ("properties", "wholes", "items")),
    "AuditPart": ("openapi", "DocumentAuditReport", ("properties", "parts", "items")),
    # Was its own component until the contract inlined it.  Pointing at the
    # property rather than at a component name also survives the reverse move:
    # if the items schema becomes a $ref again, resolve_schema_ref follows it.
    "StructuralViewCategory": (
        "openapi",
        "SchemeViewResponse",
        ("properties", "categories", "items"),
    ),
}

# Public names whose canonical source is an OpenAPI component under a
# different name.  Distinct from REF_RENAMES, which rewrites $ref targets
# encountered while rendering; this names where a model itself comes from.
COMPONENT_SOURCES = {
    "CoverageReport": "CheckCoverageResult",
    "StructuralView": "SchemeViewResponse",
    "UnmarkedSpan": "DocumentUnmarkedSpan",
    "ContextComponent": "CtxComponentDescriptor",
    "ContextDescription": "CtxDescribeResponseBody",
    "_HealthResponse": "HealthResponse",
    "_CtxListResponseBody": "CtxListResponseBody",
    "_CtxVersionsResponseBody": "CtxVersionsResponseBody",
}

# Public names sourced from a JSON Schema `definitions` entry rather than from
# an OpenAPI component.
DEFINITION_SOURCES = {"GuideRule", "FixConceptReference"}

INLINE_TYPES = {
    ("FilterResult", "categoryCounts"): "Dict[str, FilterCount]",
    ("FilterResult", "total"): "FilterCount",
    ("DocumentAuditReport", "wholes"): "List[AuditWhole]",
    ("DocumentAuditReport", "parts"): "List[AuditPart]",
}


class EnumOverride(NamedTuple):
    """A ``TYPE_OVERRIDES`` value that is still an enum position.

    ``known`` is the closed type naming the declared values. The generator
    opens it for responses the same way it opens an enum it reads from the
    schema (see ``Generator.enum_type``), so an override cannot quietly close
    a response enum again.
    """

    known: str


# Canonical schemas intentionally expose rich guide internals.  The Python
# facade has always treated these leaf declarations as opaque dictionaries;
# retaining that ergonomic boundary avoids exporting dozens of incidental
# authoring types while the surrounding wire model remains generated.
TYPE_OVERRIDES: dict[tuple[str, str], str | EnumOverride] = {
    # The discriminator of the reproducible and best-effort source variants,
    # which merge_object_union folds into one model.
    ("SourceReference", "reproducibility"): EnumOverride(
        "Literal['reproducible', 'best-effort']"
    ),
    ("RuleSourceReference", "reproducibility"): EnumOverride(
        "Literal['reproducible', 'best-effort']"
    ),
    ("Assertion", "confidence"): EnumOverride("Confidence"),
    ("GuideRule", "match"): "Optional[List[Dict[str, Any]]]",
    ("GuideRule", "outcome"): "Dict[str, Any]",
    ("GuideRule", "when"): "Optional[Union[str, List[str], Dict[str, Any]]]",
    ("GuideBreakdownEntry", "outcome"): "Dict[str, Any]",
    ("StructuralView", "categories"): "List[StructuralViewCategory]",
    # One model serves scheme views, whose entries are concepts, and guide
    # views, whose entries are rules. A concept entry typed here would refuse
    # every guide view, so the entries stay open dictionaries.
    ("StructuralViewCategory", "items"): "List[Dict[str, Any]]",
    ("StructuralView", "uncategorized"): "List[Dict[str, Any]]",
    # Scheme resource reads. Same boundary the guide internals above draw, and
    # the same one the .NET client draws on these exact fields: author-keyed
    # open maps and the recursive match DSL stay dictionaries rather than
    # exporting dozens of incidental authoring types.
    #
    # `rollup` and `sort` are authoring declarations with several shapes, and
    # `when` is the same recursive condition DSL already carried opaquely on
    # GuideRule.
    ("MarkingColorRule", "when"): "Optional[Union[str, List[str], Dict[str, Any]]]",
    ("CategoryView", "rollup"): "Any",
    ("CategoryView", "sort"): "Optional[Union[str, List[str]]]",
    ("FormatView", "mode"): EnumOverride("Literal['inline', 'block']"),
    # An open `additionalProperties` map of author-chosen keys. A generated
    # class would have zero fields and be strictly worse than the mapping.
    ("SchemeSummary", "vocabulary"): "Optional[Dict[str, Term]]",
    ("SchemeSummary", "contextFormats"): "Optional[Dict[str, List[str]]]",
    # This contract-owned payload is a discriminated union. Keep its envelope
    # typed while preserving the complete union payload as JSON until this
    # deliberately small generator supports named union variants.
    ("ContextCrosswalkTranslationResult", "result"): "Dict[str, Any]",
}


def snake(name: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).replace("-", "_").lower()
    return value + "_" if keyword.iskeyword(value) else value


class MissingSchemaSource(LookupError):
    """A public model cannot be generated from the vendored contract.

    Raised rather than a bare ``KeyError``, so a contract that dropped or
    reshaped a schema names the model, the place the schema was expected, and
    the table in this file that decides.
    """


def descend(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    for key in path:
        value = value[key]
    return value


class Generator:
    def __init__(self, spec_dir: Path) -> None:
        self.spec_dir = spec_dir
        self.json_schemas = {
            path.name.removesuffix(".schema.json"): json.loads(path.read_text())
            for path in sorted((spec_dir / "json-schemas").glob("*.schema.json"))
        }
        self.openapi = yaml.safe_load((spec_dir / "openapi.yaml").read_text())
        self.components: dict[str, dict[str, Any]] = self.openapi["components"][
            "schemas"
        ]
        self.definitions: dict[str, dict[str, Any]] = {}
        for schema in self.json_schemas.values():
            for name, definition in schema.get("definitions", {}).items():
                self.definitions.setdefault(name, definition)
        self.public = set(MODEL_ORDER)
        self.request_components = self.reachable_components("requestBody")
        self.response_components = self.reachable_components("responses")

    def reachable_components(self, part: str) -> set[str]:
        """Name every schema component reachable from one side of every operation.

        ``part`` is ``"requestBody"`` or ``"responses"``. The walk follows every
        ``#/components/<kind>/<name>`` reference transitively, so a schema is
        found whether an operation names it directly or through a shared
        component such as ``#/components/responses/BadRequest``. Only schema
        names are returned; the other component kinds are routes to them.
        """
        components: dict[str, Any] = self.openapi.get("components", {})
        found: set[str] = set()
        visited: set[tuple[str, str]] = set()
        pending: list[Any] = []
        for item in self.openapi.get("paths", {}).values():
            for operation in item.values():
                if isinstance(operation, dict) and part in operation:
                    pending.append(operation[part])
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
            elif isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/"):
                    kind, _, name = ref.removeprefix("#/components/").partition("/")
                    target = components.get(kind, {}).get(name)
                    if target is not None and (kind, name) not in visited:
                        visited.add((kind, name))
                        if kind == "schemas":
                            found.add(name)
                        pending.append(target)
                pending.extend(node.values())
        return found

    def wire_components(self, name: str) -> set[str]:
        """Name the OpenAPI components a public model stands for on the wire.

        That is the component of the same name, every component
        ``REF_RENAMES`` folds into it, and the component or parent a
        ``COMPONENT_SOURCES`` or OpenAPI ``INLINE_SOURCES`` entry reads it from.
        """
        names = {name}
        names.update(alias for alias, target in REF_RENAMES.items() if target == name)
        if name in COMPONENT_SOURCES:
            names.add(COMPONENT_SOURCES[name])
        if name in INLINE_SOURCES and INLINE_SOURCES[name][0] == "openapi":
            names.add(INLINE_SOURCES[name][1])
        return names & set(self.components)

    def component_of(self, name: str) -> str | None:
        """Name the one OpenAPI component a public model decodes, if any.

        That is its ``COMPONENT_SOURCES`` entry, else the component of the
        same name, else the single component ``REF_RENAMES`` folds into it.
        """
        if name in COMPONENT_SOURCES:
            return COMPONENT_SOURCES[name]
        if name in self.components:
            component = name
        else:
            aliases = [
                alias
                for alias, target in REF_RENAMES.items()
                if target == name and alias in self.components
            ]
            if len(aliases) > 1:
                raise MissingSchemaSource(
                    f"{name}: REF_RENAMES folds {aliases} into it; name the one it "
                    "decodes in COMPONENT_SOURCES"
                )
            if not aliases:
                return None
            component = aliases[0]
        # An enum is a value, not a body a model decodes.
        return None if "enum" in self.components[component] else component

    def directions(self, name: str) -> tuple[bool, bool]:
        """Say whether a public model travels in requests and in responses."""
        wire = self.wire_components(name)
        return (
            bool(wire & self.request_components),
            bool(wire & self.response_components),
        )

    def enum_type(self, known: str, model: str) -> str:
        """Type one enum position of a public model.

        ``known`` is the closed type naming the declared values: a ``Literal``
        or the generated ``Confidence`` enum. Requests are closed and responses
        are open, the same rule ``closure`` applies to fields, so the answer
        depends on where the OpenAPI document uses the model:

        * request bodies only: ``known`` itself. Every path refuses an
          undeclared value.
        * responses only, or no operation at all: ``Union[known, str]``. A
          value a newer server adds decodes as the string it sent.
        * both: the same union, annotated ``_KnownOnConstruction``. Decoding
          stays open, and building one with keywords, which is how a request
          is built, refuses an undeclared value.

        Raises:
            MissingSchemaSource: An ``Enum`` class on a response-only model.
                Only the construction marker maps a decoded known string back
                to its ``Enum`` member, so that shape needs a decision here
                rather than a union that silently yields bare strings.
        """
        in_request, in_response = self.directions(model)
        if in_request and not in_response:
            return known
        opened = f"Union[{known}, str]"
        if in_request:
            return f"Annotated[{opened}, _KnownOnConstruction]"
        if not known.startswith("Literal["):
            raise MissingSchemaSource(
                f"{model}: the enum {known} is response-only; decide how its "
                "known values keep their Enum type before opening it"
            )
        return opened

    def closure(self, name: str, source: dict[str, Any]) -> str:
        """Decide how a model treats fields it does not declare.

        The API evolves the Kubernetes way: requests are closed and responses
        are open, so a server can add a response field without breaking a
        client that has not been regenerated. The canonical JSON Schemas close
        many result shapes to keep the engine's own output exact, and that
        closure must not reach a model this package reads off the wire.

        Returns one of three answers for a closed schema, by where the OpenAPI
        document uses the model:

        * ``"request"``: request bodies only. The model refuses unknown fields
          everywhere (``extra="forbid"``).
        * ``"construction"``: request bodies and responses. Decoding stays
          open, and building one with keywords refuses an unknown keyword,
          which is a caller's typo that would otherwise vanish before the
          request is sent (``_ClosedOnConstruction``).
        * ``"open"``: everything else, including every response-only model.

        A model in ``CLOSED_ON_CONSTRUCTION`` is treated as closed whatever
        its schema says, and gets the first or second answer by the same
        rule.
        """
        closed = (
            name in CLOSED_ON_CONSTRUCTION
            or source.get("additionalProperties") is False
        )
        if not closed:
            return "open"
        in_request, in_response = self.directions(name)
        if in_request and in_response:
            return "construction"
        if in_request:
            return "request"
        return "open"

    def source(self, name: str) -> dict[str, Any]:
        """Resolve the canonical schema a public model is generated from.

        Raises:
            MissingSchemaSource: The configured source does not exist in the
                vendored contract, naming the model, where it was looked for,
                and the table that decides.
        """
        try:
            if name in INLINE_SOURCES:
                kind, root, path = INLINE_SOURCES[name]
                base = (
                    self.json_schemas[root] if kind == "json" else self.components[root]
                )
                return self.resolve_schema_ref(descend(base, path))
            if name in DEFINITION_SOURCES:
                return self.resolve_schema_ref(self.definitions[name])
            if name in COMPONENT_SOURCES:
                return self.resolve_schema_ref(self.components[COMPONENT_SOURCES[name]])
            if name in JSON_TOP:
                return self.resolve_schema_ref(self.json_schemas[JSON_TOP[name]])
            return self.resolve_schema_ref(self.components[name])
        except (KeyError, TypeError) as exc:
            raise MissingSchemaSource(
                f"{name}: {self.describe_source(name)} is not in the vendored "
                f"contract ({exc.__class__.__name__}: {exc})"
            ) from exc

    @staticmethod
    def describe_source(name: str) -> str:
        """Say where a public model's schema is configured to come from.

        Used in failure messages so a dropped or reshaped schema names the
        table to edit instead of surfacing as a bare lookup error.
        """
        if name in INLINE_SOURCES:
            kind, root, path = INLINE_SOURCES[name]
            document = (
                f"json-schemas/{root}.schema.json"
                if kind == "json"
                else f"components.schemas.{root}"
            )
            return f"INLINE_SOURCES -> {document}#/{'/'.join(path)}"
        if name in DEFINITION_SOURCES:
            return f"DEFINITION_SOURCES -> a JSON Schema definition named {name}"
        if name in COMPONENT_SOURCES:
            return f"COMPONENT_SOURCES -> components.schemas.{COMPONENT_SOURCES[name]}"
        if name in JSON_TOP:
            return f"JSON_TOP -> json-schemas/{JSON_TOP[name]}.schema.json"
        return (
            f"the same-named component components.schemas.{name} "
            "(no entry in JSON_TOP, INLINE_SOURCES, COMPONENT_SOURCES or "
            "DEFINITION_SOURCES)"
        )

    def unresolved_sources(self) -> list[str]:
        """Report every public model whose schema source does not resolve.

        Resolving the whole surface up front, rather than one model at a time
        mid-render, turns a contract that dropped or reshaped a schema into one
        message listing every affected model and the table that names it.
        """
        problems: list[str] = []
        for name in MODEL_ORDER:
            try:
                self.source(name)
            except MissingSchemaSource as exc:
                problems.append(f"  {exc}")
        return problems

    def stale_overrides(self) -> list[str]:
        """Report configuration that matches no schema.

        A (model, property) override whose property is gone from the contract
        does nothing at all — it neither fires nor fails, so the shipped model
        quietly stops carrying the shape the entry was written to give it.
        """
        problems: list[str] = []
        tables: list[tuple[str, Any]] = [
            ("TYPE_OVERRIDES", TYPE_OVERRIDES),
            ("INLINE_TYPES", INLINE_TYPES),
            ("DEFAULTS", DEFAULTS),
        ]
        for table_name, table in tables:
            for owner, prop in table:
                if owner not in self.public:
                    problems.append(
                        f"  {table_name}[({owner!r}, {prop!r})]: {owner} is not in "
                        "MODEL_ORDER"
                    )
                    continue
                try:
                    schema = self.merge_object_union(self.source(owner))
                except MissingSchemaSource:
                    continue  # already reported by unresolved_sources
                if prop not in schema.get("properties", {}):
                    problems.append(
                        f"  {table_name}[({owner!r}, {prop!r})]: {owner} has no "
                        f"{prop!r} property in the vendored contract"
                    )
        for table_name, names in (
            ("BASE_MIXINS", BASE_MIXINS),
            ("INLINE_SOURCES", INLINE_SOURCES),
            ("COMPONENT_SOURCES", COMPONENT_SOURCES),
            ("DEFINITION_SOURCES", DEFINITION_SOURCES),
            ("JSON_TOP", JSON_TOP),
        ):
            for owner in names:
                if owner not in self.public:
                    problems.append(
                        f"  {table_name}[{owner!r}]: not in MODEL_ORDER, so the "
                        "entry is never consulted"
                    )
        for owner, base in BASE_MODELS.items():
            for role, model in (("subclass", owner), ("base", base)):
                if model not in self.public:
                    problems.append(
                        f"  BASE_MODELS[{owner!r}]: the {role} {model} is not in "
                        "MODEL_ORDER"
                    )
            if (
                owner in self.public
                and base in self.public
                and MODEL_ORDER.index(base) > MODEL_ORDER.index(owner)
            ):
                problems.append(
                    f"  BASE_MODELS[{owner!r}]: {base} comes after {owner} in "
                    "MODEL_ORDER, so the subclass would be declared before its base"
                )
        for owner in sorted(CLOSED_ON_CONSTRUCTION):
            if owner not in self.public:
                problems.append(
                    f"  CLOSED_ON_CONSTRUCTION[{owner!r}]: not in MODEL_ORDER, so "
                    "the entry is never consulted"
                )
            elif not self.directions(owner)[0]:
                problems.append(
                    f"  CLOSED_ON_CONSTRUCTION[{owner!r}]: no request body carries "
                    f"{owner}, so there is nothing to close"
                )
        return problems

    def inheritance_conflicts(self) -> list[str]:
        """Report a subclass whose own schema disagrees with what it inherits.

        A model in ``BASE_MODELS`` inherits its base's fields rather than
        declaring them. That is only right when its own schema gives every
        shared field exactly what the base's schema gives it: the same type,
        requiredness and default, so the emitted declarations are identical.
        It also has to have every field of its base, or it would inherit one
        the contract does not give it.
        """
        problems: list[str] = []
        for owner, base in BASE_MODELS.items():
            if owner not in self.public or base not in self.public:
                continue  # already reported by stale_overrides
            try:
                own = self.field_lines(owner)
                inherited = self.field_lines(base)
            except MissingSchemaSource:
                continue  # already reported by unresolved_sources
            for wire, line in inherited.items():
                if wire not in own:
                    problems.append(
                        f"  BASE_MODELS[{owner!r}]: {owner} has no {wire!r} "
                        f"property, so it must not inherit one from {base}"
                    )
                elif own[wire] != line:
                    problems.append(
                        f"  BASE_MODELS[{owner!r}]: {owner} would declare "
                        f"`{own[wire].strip()}` but inherits "
                        f"`{line.strip()}` from {base}"
                    )
        return problems

    def preflight(self) -> None:
        """Fail loudly, once, before rendering anything.

        Raises:
            MissingSchemaSource: Some public model cannot be generated from the
                vendored contract, or some override matches no schema.
        """
        if not MODEL_ORDER:
            raise MissingSchemaSource(
                "MODEL_ORDER is empty, so this check would inspect nothing"
            )
        problems = (
            self.unresolved_sources()
            + self.stale_overrides()
            + self.inheritance_conflicts()
        )
        if problems:
            raise MissingSchemaSource(
                "the vendored contract does not match this generator's "
                "configuration:\n"
                + "\n".join(problems)
                + "\n\nEach line names the table in scripts/gen_models.py that "
                "decides it. A schema the contract dropped or renamed is "
                "repaired upstream in ezclassify/contracts or by pointing the "
                "table at its new location — never by hand-editing "
                "types/ezclassify_contract/models.py."
            )

    def resolve_schema_ref(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Resolve local schema references while preserving sibling annotations."""
        ref = schema.get("$ref")
        if not ref:
            return schema
        name = ref.rsplit("/", 1)[-1]
        if ref.startswith("#/definitions/"):
            target = self.definitions.get(name)
        elif ref.startswith("#/components/schemas/"):
            target = self.components.get(name)
        else:
            target = None
        if target is None:
            return schema
        resolved = dict(self.resolve_schema_ref(target))
        resolved.update({key: value for key, value in schema.items() if key != "$ref"})
        return resolved

    def merge_object_union(self, schema: dict[str, Any]) -> dict[str, Any]:
        variants = schema.get("anyOf") or schema.get("oneOf")
        if variants:
            variants = [self.resolve_schema_ref(variant) for variant in variants]
        if not variants or not all(v.get("type") == "object" for v in variants):
            return schema
        props: dict[str, Any] = {}
        required = set(variants[0].get("required", []))
        forbid = True
        for variant in variants:
            props.update(variant.get("properties", {}))
            required &= set(variant.get("required", []))
            forbid &= variant.get("additionalProperties") is False
        return {
            "type": "object",
            "properties": props,
            "required": sorted(required),
            "additionalProperties": False if forbid else True,
            "description": schema.get("description"),
        }

    def ref_type(self, ref: str, model: str) -> str:
        """Type a ``$ref``; ``model`` is the public model whose field it is."""
        name = ref.rsplit("/", 1)[-1]
        name = name.replace("%3C", "<").replace("%3E", ">").replace("%2C", ",")
        if name.startswith("Record<string,"):
            return "Dict[str, Any]" if "unknown" in name else "Dict[str, str]"
        name = REF_RENAMES.get(name, name)
        if name in self.public:
            return name
        component = self.components.get(name) or self.definitions.get(name)
        if component is not None:
            if "$ref" in component:
                return self.ref_type(component["$ref"], model)
            additional = component.get("additionalProperties")
            if component.get("type") == "object" and isinstance(additional, dict):
                # Resolve the value schema the same way any other schema is
                # resolved. Reading only `$ref` here dropped every map whose
                # values are a primitive to Dict[str, Any]: the moment a
                # Record<string, string> stopped being inlined and became a
                # named component, a typed map turned untyped on the public
                # surface for no reason the contract expressed.
                value = self.type_for(
                    additional, name, "additionalProperties", model=model
                )
                return f"Dict[str, {value}]"
            if component.get("enum"):
                return self.enum_type(
                    "Literal["
                    + ", ".join(repr(value) for value in component["enum"])
                    + "]",
                    model,
                )
            if "const" in component:
                return f"Literal[{component['const']!r}]"
        return "Dict[str, Any]"

    def type_for(
        self,
        schema: dict[str, Any],
        owner: str,
        prop: str,
        model: str | None = None,
    ) -> str:
        """Type one schema position.

        ``owner`` and ``prop`` key the override tables. ``model`` is the public
        model the position belongs to, which decides whether an enum there is
        open; it is ``owner`` unless a referenced component's map values are
        being typed on that model's behalf.
        """
        model = model or owner
        if (owner, prop) in TYPE_OVERRIDES:
            override = TYPE_OVERRIDES[(owner, prop)]
            if isinstance(override, str):
                return override
            return self.enum_type(override.known, model)
        if (owner, prop) in INLINE_TYPES:
            return INLINE_TYPES[(owner, prop)]
        nullable = bool(schema.get("nullable"))
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            # OpenAPI 3.1 expresses nullable scalars as a type union. Keep the
            # concrete variants so a null arm cannot widen a public field to Any.
            nullable |= "null" in schema_type
            concrete = list(dict.fromkeys(t for t in schema_type if t != "null"))
            variants = [
                self.type_for({**schema, "type": variant}, owner, prop, model)
                for variant in concrete
            ]
            if not variants:
                result = "None"
            elif len(variants) == 1:
                result = variants[0]
            else:
                result = f"Union[{', '.join(variants)}]"
        elif schema_type == "null":
            result = "None"
        elif "$ref" in schema:
            result = self.ref_type(schema["$ref"], model)
        elif schema.get("allOf"):
            choices = [
                self.type_for(item, owner, prop, model) for item in schema["allOf"]
            ]
            result = choices[0] if len(set(choices)) == 1 else "Any"
        elif schema.get("anyOf") or schema.get("oneOf"):
            union_schema = self.merge_object_union(schema)
            if union_schema is not schema:
                result = "Dict[str, Any]"
            else:
                arms = schema.get("anyOf", schema.get("oneOf"))
                nullable |= any(item.get("type") == "null" for item in arms)
                variants = [
                    self.type_for(item, owner, prop, model)
                    for item in arms
                    if item.get("type") != "null"
                ]
                if not variants:
                    result = "None"
                elif len(set(variants)) == 1:
                    result = variants[0]
                else:
                    result = f"Union[{', '.join(dict.fromkeys(variants))}]"
        elif "const" in schema:
            result = f"Literal[{schema['const']!r}]"
        elif schema.get("enum"):
            result = self.enum_type(
                "Literal[" + ", ".join(repr(value) for value in schema["enum"]) + "]",
                model,
            )
        elif schema.get("type") == "string":
            result = "str"
        elif schema.get("type") == "boolean":
            # Strict, because Pydantic's lax mode reads "false", "off" and 0 as
            # False and "yes", "on" and 1 as True. Many of these are verdicts,
            # such as `valid`, `inputWasValid` or `granted`, and a server that
            # sends anything but true or false has sent a malformed result,
            # not one this client should settle on its behalf.
            result = "StrictBool"
        elif schema.get("type") == "integer":
            result = "int"
        elif schema.get("type") == "number":
            result = "float"
        elif schema.get("type") == "array":
            result = (
                f"List[{self.type_for(schema.get('items', {}), owner, prop, model)}]"
            )
        elif schema.get("type") == "object" or "properties" in schema:
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                result = f"Dict[str, {self.type_for(additional, owner, prop, model)}]"
            else:
                result = "Dict[str, Any]"
        else:
            result = "Any"
        if nullable and result != "None" and not result.startswith("Optional["):
            result = f"Optional[{result}]"
        return result

    @staticmethod
    def summary(name: str, schema: dict[str, Any]) -> list[str]:
        """Split a schema description into the blocks of a docstring.

        The contract separates paragraphs with a blank line and puts each list
        item on a line of its own that starts with ``- ``. Each block returned
        is one paragraph, or one list item still starting with ``- ``, with
        its whitespace collapsed.
        """
        text = (schema.get("description") or f"{name} wire model.").replace(
            '"""', "'''"
        )
        blocks: list[str] = []
        for paragraph in re.split(r"\n[ \t]*\n", text.strip()):
            current: list[str] = []
            for line in paragraph.split("\n"):
                if line.lstrip().startswith("- ") and current:
                    blocks.append(" ".join(" ".join(current).split()))
                    current = []
                current.append(line)
            if current:
                blocks.append(" ".join(" ".join(current).split()))
        return blocks

    @staticmethod
    def docstring(blocks: list[str], indent: str = "    ") -> str:
        """Render a class docstring, wrapping it rather than cutting it short.

        This text is what a user reads on IDE hover and in generated API
        documentation for a published package, so it is emitted whole. Paragraphs
        keep the blank line between them, and list items stay one to a line, wrapped
        under their own text, as the contract wrote them. Lines break only at
        spaces, so a hyphenated term such as ``non-skipped`` stays whole.
        """
        width = DOCSTRING_WIDTH - len(indent)
        if len(blocks) == 1 and len(blocks[0]) + 6 <= width:
            return f'{indent}"""{blocks[0]}"""'
        body: list[str] = []
        previous_item = False
        for block in blocks:
            item = block.startswith("- ")
            if body and not (item and previous_item):
                body.append("")
            body.extend(
                textwrap.wrap(
                    block,
                    width=width,
                    subsequent_indent="  " if item else "",
                    break_on_hyphens=False,
                )
            )
            previous_item = item
        lines = [f'{indent}"""{body[0]}']
        lines.extend(f"{indent}{line}" if line else "" for line in body[1:])
        lines.append(f'{indent}"""')
        return "\n".join(lines)

    @staticmethod
    def bases(name: str, closure: str) -> list[str]:
        """The base classes a model is declared with, in MRO order."""
        bases = [BASE_MIXINS[name]] if name in BASE_MIXINS else []
        if name in BASE_MODELS:
            bases.append(BASE_MODELS[name])
        if closure == "construction":
            bases.append("_ClosedOnConstruction")
        return bases or ["_WireModel"]

    def render_class(self, name: str) -> str:
        source = self.source(name)
        if name == "Confidence":
            values = source["enum"]
            lines = [
                f"class {name}(str, Enum):",
                self.docstring(self.summary(name, source)),
                "",
            ]
            lines.extend(f"    {value} = {value!r}" for value in values)
            return "\n".join(lines)

        source = self.merge_object_union(source)
        closure = self.closure(name, source)
        bases = self.bases(name, closure)
        lines = [
            f"class {name}({', '.join(bases)}):",
            self.docstring(self.summary(name, source)),
            "",
        ]
        if closure == "request":
            lines.extend(
                [
                    '    model_config = ConfigDict(populate_by_name=True, extra="forbid")',
                    "",
                ]
            )
        fields = self.field_lines(name, documented=True)
        if name in BASE_MODELS:
            base = BASE_MODELS[name]
            inherited = self.field_lines(base)
            fields = {
                wire: line for wire, line in fields.items() if wire not in inherited
            }
        lines.extend(fields.values())
        if not fields:
            lines.append("    pass")
        return "\n".join(lines)

    def field_lines(self, name: str, documented: bool = False) -> dict[str, str]:
        """Declare each wire field of a public model, keyed by its wire name.

        With ``documented``, a field the contract describes is followed by its
        description as an attribute docstring: what IDE hover and API
        documentation show for the field. It is not part of the model's
        behavior, so declarations are compared without it.
        """
        source = self.merge_object_union(self.source(name))
        lines: dict[str, str] = {}
        props: dict[str, dict[str, Any]] = source.get("properties", {})
        required = set(source.get("required", []))
        for wire, field_schema in props.items():
            field_name = snake(wire)
            annotation = self.type_for(field_schema, name, wire)
            is_required = wire in required
            default = DEFAULTS.get((name, wire))
            if (
                not is_required
                and not annotation.startswith("Optional[")
                and default is None
            ):
                annotation = f"Optional[{annotation}]"
            alias = wire if field_name.rstrip("_") != wire else None
            if default == "factory":
                args = [
                    "default_factory=list"
                    if annotation.replace("Optional[", "").startswith("List[")
                    else "default_factory=dict"
                ]
                if alias:
                    args.append(f"alias={alias!r}")
                rhs = f" = Field({', '.join(args)})"
            elif default is not None:
                rhs = (
                    f" = Field({default}, alias={alias!r})"
                    if alias
                    else f" = {default}"
                )
            elif is_required:
                rhs = f" = Field(alias={alias!r})" if alias else ""
            else:
                rhs = f" = Field(default=None, alias={alias!r})" if alias else " = None"
            line = f"    {field_name}: {annotation}{rhs}"
            if documented and field_schema.get("description"):
                line += "\n" + self.docstring(self.summary(wire, field_schema))
            lines[wire] = line
        return lines

    def generate(self) -> str:
        self.preflight()
        contract_hash = hashlib.sha256()
        for path in [
            self.spec_dir / "openapi.yaml",
            *sorted((self.spec_dir / "json-schemas").glob("*.schema.json")),
        ]:
            contract_hash.update(path.read_bytes())
        header = f'''# Code generated from vendored contracts@{contract_hash.hexdigest()}. DO NOT EDIT.
"""Pydantic models generated from EzClassify's vendored OpenAPI and JSON Schemas."""

from __future__ import annotations

from enum import Enum
from typing import {{typing}}

from pydantic import {{pydantic}}

from ._model_helpers import (
{{helpers}})
'''
        classes = [self.render_class(name) for name in MODEL_ORDER]
        pydantic_names = ["ConfigDict", "Field"]
        if any("StrictBool" in block for block in classes):
            pydantic_names.append("StrictBool")
        header = header.replace("{pydantic}", ", ".join(pydantic_names))
        used = {"_WireModel", *BASE_MIXINS.values()}
        if any("_ClosedOnConstruction" in block.split("\n", 1)[0] for block in classes):
            used.add("_ClosedOnConstruction")
        typing_names = ["Any", "Dict", "List", "Literal", "Optional", "Union"]
        if any("_KnownOnConstruction]" in block for block in classes):
            used.add("_KnownOnConstruction")
            typing_names.insert(0, "Annotated")
        header = header.replace("{typing}", ", ".join(typing_names))
        header = header.replace(
            "{helpers}", "".join(f"    {helper},\n" for helper in sorted(used))
        )
        body = header + "\n\n".join(classes)
        body += "\n\n\n# Resolve postponed references after every generated declaration exists.\n"
        body += (
            "for _model_name in "
            + repr([name for name in MODEL_ORDER if name != "Confidence"])
            + ":\n"
        )
        body += "    globals()[_model_name].model_rebuild()\n"
        body += "del _model_name\n"
        body += self.wire_shapes()
        return body

    def wire_shapes(self) -> str:
        """Render the required-member table ``from_dict`` checks responses with.

        Each public model generated from an OpenAPI component decodes that
        component's shape. A model with no component of its own (a JSON
        Schema top-level or definition, or an inline object) only appears
        nested inside one, whose shape already covers it.
        """
        shapes = WireShapes(self.components)
        models: dict[str, str] = {}
        for name in MODEL_ORDER:
            component = self.component_of(name)
            if component is None:
                continue
            shapes.component(component)
            models[name] = component
        return shapes.render(models)


class WireShapes:
    """Compile the OpenAPI document's required members into a decoding table.

    A response that lacks a member the contract requires, or carries null
    where the contract does not allow it, is malformed wherever the member
    sits. The generated models cannot say so on their own: some positions are
    deliberately open dictionaries (``TYPE_OVERRIDES``), and some required
    members carry a default so a caller building a model with keywords can
    leave them out. This table carries the contract's own answer, read from
    ``components.schemas`` and nothing else, for ``from_dict`` to check before
    a model is validated.

    A shape is ``None`` (nothing below it is required), the name of a
    component's shape, or a dict with these keys, each present only when it
    has something to say:

    ``r``
        The required members, in declaration order, each as ``(name,
        nullable)``.
    ``p``
        The declared members whose own shapes require something.
    ``v`` and ``d``
        The shape of the values of undeclared members, and every declared
        member name, which those values exclude.
    ``i``
        The shape of an array's items.
    ``u``
        The alternatives of an ``anyOf`` or ``oneOf``, each a shape with its
        kind ``k`` (``object`` or ``array``) and the constants ``c`` that name
        it, each as the values that member may hold (one for a constant,
        several for an enum). A null alternative is not listed: whether null
        is allowed is the enclosing member's ``nullable``.
    """

    def __init__(self, components: dict[str, dict[str, Any]]) -> None:
        self.components = components
        self.shapes: dict[str, Any] = {}
        self._compiling: set[str] = set()

    def _target(self, schema: Any) -> Any:
        while isinstance(schema, dict) and "$ref" in schema:
            schema = self.components[schema["$ref"].rsplit("/", 1)[-1]]
        return schema

    def allows_null(self, schema: Any) -> bool:
        """Say whether a member with this schema may be null."""
        schema = self._target(schema)
        if not isinstance(schema, dict) or not schema:
            return True
        kind = schema.get("type")
        if kind == "null" or (isinstance(kind, list) and "null" in kind):
            return True
        if schema.get("nullable") is True:
            return True
        alternatives = schema.get("anyOf") or schema.get("oneOf")
        if alternatives:
            return any(self.allows_null(item) for item in alternatives)
        return "const" in schema and schema["const"] is None

    def component(self, name: str) -> str | None:
        """Compile one component and return its table key, or ``None``."""
        if name in self.shapes:
            return name if self.shapes[name] is not None else None
        if name in self._compiling:
            # A recursive schema: refer to it by name. If it turns out to
            # require nothing it gets no table entry, and a name with no
            # entry resolves to nothing when a body is checked.
            return name
        self._compiling.add(name)
        try:
            shape = self.compile(self.components[name])
        finally:
            self._compiling.discard(name)
        self.shapes[name] = shape
        return name if shape is not None else None

    def compile(self, schema: Any) -> Any:
        """Compile one schema position to its shape."""
        if not isinstance(schema, dict):
            return None
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            return self.component(ref.rsplit("/", 1)[-1])
        if "allOf" in schema:
            raise MissingSchemaSource(
                "WireShapes reads no allOf; teach it before the contract uses one"
            )
        alternatives = schema.get("anyOf") or schema.get("oneOf")
        if alternatives:
            if "properties" in schema or "required" in schema:
                raise MissingSchemaSource(
                    "WireShapes reads no union that also declares members"
                )
            return self._union(alternatives)
        kind = schema.get("type")
        if isinstance(kind, list) and {"object", "array"} & set(kind):
            raise MissingSchemaSource(
                f"WireShapes reads no type list holding a container: {kind}"
            )
        shape: dict[str, Any] = {}
        properties: dict[str, Any] = schema.get("properties", {})
        required = [
            (name, self.allows_null(properties.get(name)))
            for name in schema.get("required", [])
        ]
        if required:
            shape["r"] = required
        members = {
            name: child
            for name, child in (
                (name, self.compile(member)) for name, member in properties.items()
            )
            if child is not None
        }
        if members:
            shape["p"] = members
        additional = schema.get("additionalProperties")
        values = self.compile(additional) if isinstance(additional, dict) else None
        if values is not None:
            shape["v"] = values
            shape["d"] = list(properties)
        items = self.compile(schema.get("items"))
        if items is not None:
            shape["i"] = items
        return shape or None

    def _union(self, alternatives: list[Any]) -> Any:
        entries: list[tuple[str, dict[str, Any], Any]] = []
        for alternative in alternatives:
            target = self._target(alternative)
            if not isinstance(target, dict):
                continue
            kind = target.get("type")
            if kind is None and "properties" in target:
                kind = "object"
            if kind is None and ("anyOf" in target or "oneOf" in target):
                raise MissingSchemaSource(
                    "WireShapes reads no union nested directly in a union"
                )
            if kind not in ("object", "array"):
                # A null or scalar alternative requires nothing below it.
                continue
            entries.append((kind, target, self.compile(alternative)))
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0][2]
        compiled: list[dict[str, Any]] = []
        for kind, target, shape in entries:
            entry: dict[str, Any] = {"k": kind}
            if isinstance(shape, str):
                entry["s"] = shape
            elif shape:
                entry.update(shape)
            properties: dict[str, Any] = target.get("properties", {})
            consts: dict[str, list[Any]] = {}
            for name, member in properties.items():
                member = self._target(member)
                if isinstance(member, dict) and "const" in member:
                    consts[name] = [member["const"]]
                elif isinstance(member, dict) and "enum" in member:
                    consts[name] = list(member["enum"])
            if consts:
                entry["c"] = consts
            if kind == "object" and "r" not in entry and target.get("required"):
                # Choosing an alternative reads its required names, so a
                # referenced alternative carries them beside its shape.
                entry["r"] = [
                    (name, self.allows_null(properties.get(name)))
                    for name in target["required"]
                ]
            compiled.append(entry)
        if all(set(entry) == {"k"} for entry in compiled):
            return None
        return {"u": compiled}

    def render(self, models: dict[str, str]) -> str:
        """Render the table and the model-to-shape map as Python source."""
        keys = sorted(name for name, shape in self.shapes.items() if shape is not None)
        lines = [
            "",
            "",
            "# The contract's required members, for from_dict to check before a model",
            "# validates a response. Generated from components.schemas; see",
            "# _model_helpers._check_wire_shape for how a shape is read.",
        ]
        # pformat keeps declaration order and wraps at the docstring width, so
        # a reviewer can read one component's members off the diff.
        table = pprint.pformat(
            {name: self.shapes[name] for name in keys},
            width=DOCSTRING_WIDTH,
            sort_dicts=False,
        )
        lines.append(f"_WIRE_SHAPES: Dict[str, Any] = {table}")
        lines.append("")
        lines.append(
            "# The OpenAPI component each public model is generated from, where"
        )
        lines.append(
            "# it has one. A component that requires nothing has no table entry."
        )
        lines.append("_MODEL_SHAPES: Dict[str, str] = {")
        lines.extend(f"    {model!r}: {shape!r}," for model, shape in models.items())
        lines.append("}")
        return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_dir", nargs="?", default="vendor/spec")
    args = parser.parse_args()
    try:
        output = Generator((ROOT / args.spec_dir).resolve()).generate()
    except MissingSchemaSource as exc:
        # A stack trace here says nothing the message does not, and buries it.
        print(f"gen_models: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    OUT.write_text(output, encoding="utf-8")
    print(f"Generated shipped models: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
