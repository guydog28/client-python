# Code generated from vendored contracts@517abc69fa5e8f33006006cb852c96274e0a70e3fdc989d8c419f900baabeb7f. DO NOT EDIT.
"""Pydantic models generated from EzClassify's vendored OpenAPI and JSON Schemas."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import ConfigDict, Field, StrictBool

from ._model_helpers import (
    _ClosedOnConstruction,
    _ContextDescriptionMixin,
    _KnownOnConstruction,
    _SourceIdentityMixin,
    _WireModel,
)
class Confidence(str, Enum):
    """How the assertion was produced: `certain` when read or handed in as stated,
    `inferred` when an inference rule added it, or `repaired` when the engine added or
    rewrote it while repairing the marking. The engine does not assign `uncertain`
    itself.
    """

    certain = 'certain'
    inferred = 'inferred'
    repaired = 'repaired'
    uncertain = 'uncertain'

class Attribution(_WireModel):
    """Provenance attached to every source so downstream consumers can render proper
    attribution and license notices.

    Mandatory because most source data we'll integrate (NIST, ICS, IANA, external
    taxonomies) requires citation. Sources that don't have a formal license should set
    `license: 'unspecified'` rather than omit it.
    """

    name: str
    """Display name of the upstream source (e.g. "NIST CSWP-29")."""
    license: str
    """SPDX identifier or short license token (e.g. "CC-BY-4.0", "public-domain")."""
    license_url: Optional[str] = Field(default=None, alias='licenseUrl')
    """Canonical URL where the license terms can be inspected."""
    citation: Optional[str] = None
    """Suggested citation string for academic / regulatory use."""

class ArtifactReference(_WireModel):
    """Identifies an immutable artifact participating in a composed operation."""

    kind: Annotated[Union[Literal['scheme', 'layer', 'guide', 'access', 'crosswalk', 'context'], str], _KnownOnConstruction]
    """Artifact family."""
    id: str
    """Artifact identifier."""
    version: str
    """Resolved immutable artifact version."""
    digest: Optional[str] = None
    """Content digest when the resolver can supply one."""

class SourceReference(_SourceIdentityMixin):
    """Records source identity and mandatory attribution for an operation."""

    reproducibility: Annotated[Union[Literal['reproducible', 'best-effort'], str], _KnownOnConstruction]
    """Whether the source observation can be reproduced byte-for-byte."""
    snapshot_id: Optional[str] = Field(default=None, alias='snapshotId')
    """Immutable content identity."""
    locator: Optional[str] = None
    """Location from which the mutable content was observed."""
    provider_id: str = Field(alias='providerId')
    """Stable identifier for the source provider."""
    attribution: Attribution
    """Attribution and license information for the observed source."""

class RuleSourceReference(_SourceIdentityMixin):
    """Compact source join carried by a qualified rule reference."""

    provider_id: str = Field(alias='providerId')
    """Stable identifier for the source provider."""
    reproducibility: Annotated[Union[Literal['reproducible', 'best-effort'], str], _KnownOnConstruction]
    """Whether the source observation can be reproduced byte-for-byte."""
    snapshot_id: Optional[str] = Field(default=None, alias='snapshotId')
    """Immutable snapshot containing the rule."""

class RuleReference(_WireModel):
    """Identifies the exact resolved semantics of one policy rule."""

    artifact: ArtifactReference
    """Artifact that owns the rule."""
    rule_id: str = Field(alias='ruleId')
    """Rule identifier within the owning artifact."""
    rule_digest: str = Field(alias='ruleDigest')
    """RFC 8785/SHA-256 digest of the canonical resolved rule content."""
    source: Optional[RuleSourceReference] = None
    """External source identity when the rule was not supplied inline."""

class AssertionReference(_WireModel):
    """Compact reference to an assertion without engine-production metadata."""

    category_id: str = Field(alias='categoryId')
    """Category containing the asserted concept."""
    concept_id: str = Field(alias='conceptId')
    """Asserted concept identifier."""
    value: Optional[str] = None
    """Captured value for value-bearing concepts."""

class AccessOperand(_WireModel):
    """Typed operand captured while an access rule is evaluated."""

    source: Union[Literal['subject', 'context', 'assertion', 'literal'], str]
    """Source domain from which the value was read."""
    path: Optional[str] = None
    """Dot-path for subject or context operands."""
    category_id: Optional[str] = Field(default=None, alias='categoryId')
    """Category addressed by an assertion operand."""
    assertions: Optional[List[AssertionReference]] = None
    """Assertions addressed by an assertion operand."""
    value: Optional[Any] = None
    """Literal or resolved opaque value."""

class AccessComparisonResult(_WireModel):
    """Machine-readable result of one access-rule comparison."""

    left: AccessOperand
    """Left comparison operand."""
    operator: str
    """Policy operator applied to the operands."""
    right: AccessOperand
    """Right comparison operand."""
    matched: StrictBool
    """Whether the comparison succeeded."""
    missing: Optional[List[Any]] = None
    """Required values missing from the evaluated operand, when applicable."""

class AccessRuleActivation(_WireModel):
    """Machine-readable record of why an access rule activated."""

    matched: StrictBool
    """Whether the rule's activation predicate matched."""
    assertions: List[AssertionReference]
    """Assertions that activated the rule."""
    context_paths: List[str] = Field(alias='contextPaths')
    """Context paths consulted by activation."""

class Assertion(_ClosedOnConstruction):
    """A concept asserted in a category during processing, with confidence level and
    provenance metadata.

    Assertions are the core data unit flowing through the engine pipeline. `confidence`
    records how the assertion was produced: `'certain'` when read or handed in as
    stated, `'inferred'` when an inference rule added it, and `'repaired'` when the
    engine added or rewrote it while repairing the marking. The engine does not assign
    `'uncertain'` itself. `source` says where the assertion came from. `expiresAt`
    records caller-supplied expiry metadata. The engine does not evaluate that date or
    automatically change confidence or the marking; the host applies its expiry policy.
    """

    category_id: str = Field(alias='categoryId')
    """The id of the category the concept is asserted in."""
    concept_id: str = Field(alias='conceptId')
    """The id of the concept."""
    confidence: Annotated[Union[Confidence, str], _KnownOnConstruction] = Confidence.certain
    """How the assertion was produced: `certain` when read or handed in as stated,
    `inferred` when an inference rule added it, or `repaired` when the engine added or
    rewrote it while repairing the marking. The engine does not assign `uncertain`
    itself.
    """
    expires_at: Optional[str] = Field(default=None, alias='expiresAt')
    """Caller-supplied ISO 8601 expiry date; the engine does not evaluate it."""
    metadata: Optional[Dict[str, Any]] = None
    """Caller-defined data attached to the assertion. The engine assigns it no meaning.
    """
    provenance: Optional[SourceReference] = None
    """Source provenance for the concept that backed this assertion.

    Populated only when the concept came from an external source whose records were
    loaded with the scheme (typically one a scheme's `concepts.external` block
    declares). Inline-backed assertions leave this field undefined to keep payloads
    compact for the common single-source case. A concept a scheme document declares in
    its `inline` list has none, even when one of that document's `external` sources also
    serves a record with its id. A concept read through a queryable-only source
    (`SourceCapabilities.queryableOnly`) has none either: that source is asked per
    lookup and never loaded whole, and a lookup does not say which source answered. Such
    a source still appears in a composed operation's `resolution.sources`. Across a
    layered stack the later layer decides: a concept a later layer's source supplies
    carries that source's provenance even when an earlier document declares it inline,
    and a concept a later layer declares inline carries none.

    Identity fields mirror the source's `sourceIdentity()` observation at engine-load
    time (or the immutable value the Context pinned).
    """
    replaced_concept_id: Optional[str] = Field(default=None, alias='replacedConceptId')
    """The deprecated concept this assertion was modernized from.

    Set when processing rewrote a deprecated concept into the replacement its scheme
    declares. `conceptId` is the current concept every downstream stage evaluates; this
    field records what the data was actually marked with, so an explanation can show the
    substitution ("concept A was replaced by concept B; B is what your access was
    compared against") instead of silently presenting a concept the document never
    carried.

    It travels on the assertion rather than alongside it because assertion arrays are
    the engine's state transport: an access check made from transported assertions can
    still explain the substitution.
    """
    source: str = "parse"
    """Where this assertion came from. An open string: the engine labels the facts it adds,
    and a caller or a host may label the facts it hands in however it likes.

    Four labels mean the engine derived the fact, so it derives the fact again each time
    it settles a marking: `infer`, and `repair` with a `sourceRule`, a fact a scheme
    rule adds; `default`, a category's default concept; and `context`, a value a part
    took from its whole. When validate, process or explain settles a marking, a fact
    handed in under one of them is set aside and comes back only if the engine derives
    it again, so no label can make a removal silent.

    Every other label is the author's statement and is kept as given: `parse` (read from
    text), `user` (handed in by a caller), `aggregate` (a value a rollup states as its
    own, even one a contributor derived or took from its whole), every other label the
    engine writes on a result, and any label a caller or host chooses, such as `stated`.
    """
    source_rule: Optional[str] = Field(default=None, alias='sourceRule')
    """The id of the scheme rule that produced this assertion, when one did. Otherwise an
    engine-owned id beginning with `_`, set when the scheme's structure, not a rule,
    added the assertion. The engine writes two: `_tier_child_requires_parent` (a tier
    parent required by a stated child) and `_header_of_stated_member` (a header filled
    in for a stated member). A scheme rule id never begins with `_`.
    """
    value: Optional[str] = None
    """The value of a concept that takes one (`text_input`).

    A value handed in is read the way a value in text is: it settles in the spelling the
    concept's encoding stores. One the encoding cannot read is reported as the error
    `_invalid_assertion_value`, and a concept that takes a value, handed in with none,
    as `_missing_assertion_value`. See `ValidationError`.
    """

class ValidationError(_WireModel):
    """A constraint violation detected during validation, referencing the constraint ID and
    a human-readable message.

    Carried in the `errors` of every result that judges a marking. `constraintId`
    identifies the rule that fired; `message` is human-readable. When `severity` is
    `'warning'`, the violation is advisory and does not set `valid` to `false`. Use
    `categoryId` and `affectedConcepts` to highlight the specific UI elements involved.

    Two of the ids the engine keeps for itself are for a fact a caller hands in that
    cannot be settled as given: `_missing_assertion_value`, a concept that takes a value
    handed in with none, and `_invalid_assertion_value`, a value the concept's encoding
    cannot read. Each is an error on the result, not a refused request: the fact is left
    out of the settled marking and named in `affectedConcepts`.

    Another, `_exceeds_whole`, is a part that carries more than the whole it is read in:
    the whole does not cover a value the part holds, carries one the part does not
    allow, or, in a category a rollup pipeline resolves, would change if rolled up with
    the part. It is given only for a part that is valid on its own, read in a whole that
    reads and is valid. `affectedConcepts` names every finding, and no fix answers it.
    See `ProcessingContext.partOf`.
    """

    affected_concepts: Optional[List[str]] = Field(default=None, alias='affectedConcepts')
    """Concept IDs involved in this validation failure."""
    category_id: Optional[str] = Field(default=None, alias='categoryId')
    """Category ID this error relates to (when determinable from the constraint)."""
    constraint_id: str = Field(alias='constraintId')
    """The id of the constraint that was violated: a scheme rule's id, or an
    engine-reserved id beginning with `_`.
    """
    did_you_mean: Optional[List[str]] = Field(default=None, alias='didYouMean')
    """The ids of the concepts the unread token was likely meant as. Never empty. They are
    ids for a program to act on, not spellings to show an author: `message` gives the
    same hint in words, naming the spellings.

    Set only on an `_unmatched_token` error, which is about one token the engine could
    not read, and only when that token reads as a misspelling of some concept's
    spelling. The concepts named are tied for nearest, so their order ranks none above
    another.

    Its absence is no evidence that the token is stray text. A token too short to judge
    carries none, and so does one equally near to too many concepts. A token that
    already spells a concept, apart from case, carries none even when it is also near
    another concept: it was left unread for another reason, such as where it stands, and
    naming a different concept would point the author away from a word they spelled
    right.

    It is not a fix: nothing here has been proven to make the marking valid, and
    `suggestedFix` and the result's fix paths do not depend on it.
    """
    message: str
    """What is wrong, in words a person can act on."""
    severity: Optional[Union[Literal['error', 'warning'], str]] = None
    """Severity: 'error' blocks validity, 'warning' is advisory. Default: 'error'."""
    suggested_fix: Optional[str] = Field(default=None, alias='suggestedFix')
    """The `message` of the proposed fix that answers this error, such as "Add CTRL-A".

    Set only on a result that carries that fix in its own `proposedFixes`. A result with
    no fix paths, such as a `ValidateResult` or a scan region, never sets it, so a
    reader never holds a pointer to a fix it was not given.
    """

class EngineWarning(_WireModel):
    """A non-blocking informational signal surfaced in a result's `warnings`.

    Unlike `ValidationError`, warnings never affect `valid`. `kind: 'deprecation'` fires
    when a deprecated concept is asserted, and `replacement` names a suggested successor
    concept. `kind: 'rule'` fires when a scheme's authored `warn` rule matches the
    marking, with the rule's id as `ruleId`. `kind: 'notice'` is the engine speaking
    about the operation itself rather than about anything the scheme declares; its
    `ruleId`, when present, is an engine-reserved id beginning with `_`, the same
    convention a `ValidationError` follows.

    A marking's warnings come in a fixed order: deprecations first, then the scheme's
    rule warnings in the order the scheme declares its rules, then the engine's notices.
    An aggregate's warnings are about the rolled-up marking, not about each marking that
    fed it.
    """

    category_id: Optional[str] = Field(default=None, alias='categoryId')
    """Category this warning relates to (when applicable)"""
    concept_id: Optional[str] = Field(default=None, alias='conceptId')
    """Concept this warning relates to (when applicable). A rule warning names one when the
    rule's `when` names exactly one concept the marking holds.
    """
    concept_name: Optional[str] = Field(default=None, alias='conceptName')
    """Resolved operational display for `conceptId` (the concept's rendered marking view),
    for a consumer that shows the warning next to the concept. `conceptId` stays as the
    machine key; this is the human-visible string.
    """
    kind: Union[Literal['deprecation', 'rule', 'notice'], str]
    """Warning kind: 'deprecation' for a deprecated concept, 'rule' for a scheme's authored
    `warn` rule, 'notice' for the engine's own notice.
    """
    message: str
    """Human-readable message"""
    replacement: Optional[str] = None
    """When kind=deprecation, the suggested replacement concept id (if any)"""
    replacement_name: Optional[str] = Field(default=None, alias='replacementName')
    """When kind=deprecation, the resolved operational display for `replacement` (the
    successor concept's rendered marking view). `replacement` stays as the machine key;
    this is the human-visible string.
    """
    rule_id: Optional[str] = Field(default=None, alias='ruleId')
    """The scheme rule that gave a `rule` warning, or the engine-reserved id of a `notice`.
    Absent on a deprecation warning.
    """

class FixConceptReference(_WireModel):
    """Stable reference to a concept a fix or change touches."""

    category_id: str = Field(alias='categoryId')
    """Owning category identifier."""
    concept_id: str = Field(alias='conceptId')
    """Concept identifier."""

class Fix(_WireModel):
    """One way to make the marking valid. Every change in it answers an error.

    A fix is a whole marking, not a patch: `rendered` is the complete marking the author
    would end up with. The engine proves each one before offering it: it reads the
    marking back, judges it the way it judges any input, and offers only those that read
    back valid.
    """

    adds: List[FixConceptReference]
    """Concepts this fix adds because an error requires them."""
    keeps: List[FixConceptReference]
    """Concepts of the author's marking this fix keeps."""
    message: str
    """What this fix does, in words."""
    removes: List[FixConceptReference]
    """Concepts of the author's marking this fix removes because an error names them."""
    rendered: str
    """The valid marking this fix produces, in the result's output format.

    It is written exactly as the result's own `rendered` is, so the two can be shown
    side by side. On an in-process engine with an `afterRender` plugin, that includes
    the plugin; the proof reads back the engine's own writing from before the plugin
    ran, so the plugin never decides which fixes are offered.
    """

class Change(_WireModel):
    """A change the engine actually made while processing. Lives in `appliedFixes`; a
    declined addition is not a change.
    """

    action: Union[Literal['add', 'remove', 'replace', 'reorder'], str]
    """'add' (only `add` set), 'remove' (only `remove` set), 'replace' (both), 'reorder'
    (neither: the input parsed via a tolerant rule; the canonical form is in the
    result's `rendered`).
    """
    add: Optional[List[FixConceptReference]] = None
    """Concepts the change added. Set for `add` and `replace`."""
    message: str
    """What the change did, in words."""
    remove: Optional[List[FixConceptReference]] = None
    """Concepts the change removed. Set for `remove` and `replace`."""
    rule_id: str = Field(alias='ruleId')
    """Rule that made this change: a scheme rule's id, or an id the engine keeps for a
    change no scheme rule names.

    `_recognition_role` is one of them: the text was read as a view of one role, for a
    request whose context names the other. See `ValidateResult.inputWasValid`, and
    `ValidateResult.appliedFixes` for how it is shown.
    """
    trigger_concept_ids: Optional[List[str]] = Field(default=None, alias='triggerConceptIds')
    """Concept IDs whose presence triggered the rule that made this change."""

class ConceptColor(_WireModel):
    """Portable scheme-default display colors, carried as a text/background pair so
    contrast is authored together. In category mode they are declared only on concepts
    in the category named by `render.color_from`; consuming hosts may override them.

    Both values are CSS hex (`#rgb` or `#rrggbb`). The pair travels together so a host
    never composes one authored color against an unknown surface (the white-on-white
    failure mode).
    """

    background: str
    """Background color as a CSS hex string."""
    text: str
    """Text/foreground color as a CSS hex string."""

class ValidateResult(_WireModel):
    """What validate answers about one marking: the facts it states once settled, whether
    they stand, and what a reader needs to show why not.

    Validate is the reader's call. A host that displays a marking, gates on it, stores
    it, or hands its facts to an access check or a rollup calls it. The result carries
    no fix paths, no corrections to the text and no output beyond the one rendering,
    because a reader is not writing the marking. The author's call is process, and a
    `ProcessResult` is this result with the authoring answers added.

    Each field means the same wherever it appears: on a validate or process result, on
    each region of a scan, in-process or over a wire.

    Scheme and engine metadata (schemeVersion, schemeId) are not on the result; read
    them from `engine.version`, `engine.scheme.id` and `engine.scheme.version` instead.
    """

    applied_fixes: List[Change] = Field(alias='appliedFixes')
    """Every change the engine actually made while settling the marking: a departure from
    canonical spelling or order that recognition read through, a repair, a fact a rule
    required, a handed-in fact settling removed, or text read in the other role from the
    one the request names. A removed fact is named with the reason it was removed,
    including a fact handed in with a derived source label that the run does not derive
    again. A requirement that conflicts with an existing concept is not added and
    appears in errors and proposed fixes, with no applied change. Repair never removes
    an author-stated concept. These are the reasons a marking can be `valid` while
    `inputWasValid` is false.

    A departure from spelling or order is reported here without a position. On a process
    result, `recognition.corrections` reports the same departure with the span of the
    text it covers. They are one change seen two ways, so a display shows one of them,
    not both. The role departure, `_recognition_role`, is about the whole text: it has
    no span and no entry in `recognition.corrections`, so it is reported only here, and
    a display that shows corrections in place of this list still shows it.
    """
    assertions: List[Assertion]
    """The facts the marking states, as the engine settled them.

    Listed in print order: the order the rendered marking places each concept; a concept
    the rendering leaves out appears where it would print. A concept the rendering has
    no place for at all follows the others of its category, or comes last when its
    category has none, in the order the scheme declares.
    """
    assessment: Dict[str, Any]
    """The assessment of `rendered`: what it wrote of these facts, what it left out, what
    collapsed into an equivalent, and what it could not write at all. When `rendered`
    carries more than one surface, this is the combined assessment `RenderResult`
    describes. Read it before treating `rendered` as a transport.
    """
    display_color: Optional[ConceptColor] = Field(default=None, alias='displayColor')
    """Portable scheme-derived display color for the settled marking. Embedding hosts may
    override this presentation default.
    """
    errors: List[ValidationError]
    """What the scheme's rules find wrong with the settled marking. An entry whose severity
    is `error` makes `valid` false.

    No entry here points at a fix path: `suggestedFix` is set only on a result that
    carries the fix it names, and this result carries none.
    """
    input_was_valid: StrictBool = Field(alias='inputWasValid')
    """True when the text or facts as given needed no change to stand.

    Defined here once, and judged after the same settling as `valid`. A marking can be
    `valid` without having been valid as given: the engine settled it into one that
    stands. A result whose `inputWasValid` is false always says why: each change the
    engine made is in `appliedFixes`, and whatever it could not settle is in `errors`.

    Right as written is judged against the view the text was read as, the one
    `recognition.inputFormat` reports, or for text read on more than one surface, the
    view each surface's part was read as. A fact settling adds, including a restored
    tier parent, counts against it only when that view writes the fact. A view that
    leaves the fact out writes the same text with the fact as without it, so the text
    was right already. Text read as no single view counts the fact when any view that
    read it writes it. Facts handed in with no text are judged against what a request
    that names no output writes them in, by the rule `rendered` follows.

    Text is also not right as written when the request's context names a role and
    recognition decided the text is a view of the other role, as `recognition.role`
    reports. The result carries that departure in `appliedFixes` under
    `_recognition_role`, and `valid` is judged as it would be without it. A request that
    names its input format has said which view the text is: the text is judged as that
    view, and no role departure is raised. On a scan region and on a marking a document
    audit judges, the role the marking's place gives it stands for the context's role: a
    region found inside a wrapper is a part, and an audit judges each marking in the
    role it has in the document.
    """
    notices: List[Notice]
    """The notices the scheme attaches to the concepts in `assertions`, collected the same
    way `SchemeEngine.collectNotices()` collects them. Always present, empty when the
    marking carries none, so a consumer can read the field without checking that it
    exists.
    """
    recognition: Optional[Dict[str, Any]] = None
    """What recognition made of the text: how far it got, what it read the text as, and
    what it could not account for.

    Present exactly when there was text to recognize. Given facts, nothing was read, and
    the field is absent rather than carrying a made-up status about an input that does
    not exist. The same holds for every other result built from carried facts, notably a
    crosswalk's target.
    """
    rendered: str
    """The settled marking, in one string.

    It is written in the output the request names. With none named, a scheme without
    `render.surfaces` writes its default format, and a scheme with them writes each
    surface in its default for the marking's role, by the rule
    `RenderConfigDoc.surfaces` states. Every operation that returns this shape follows
    that one rule.

    For a scheme that declares `render.surfaces`, the string is the output resolved on
    each surface the result writes, as `RenderConfigDoc.surfaces` describes, in declared
    surface order and joined by `render.surface_separator`. An output that writes
    nothing adds nothing, and outputs written as XML attributes in one namespace merge
    into one attribute list. One refused output refuses the whole string, and
    `assessment` says which one and why.
    """
    valid: StrictBool
    """True when the marking stands once the engine has settled it: read, repaired,
    completed by what the scheme's rules imply, and judged with no error left.

    Defined here once, and every result that reports `valid` means this, whichever
    operation produced it and whichever door it came through. Reading is tolerant on
    purpose, so the engine settles what it can. Whether the text was right as written is
    what `inputWasValid` and `appliedFixes` answer; no request asks the engine to settle
    less, so validate and process give the same `valid` for the same input, context,
    surface and parts.
    """
    warnings: List[EngineWarning]
    """Advisories that do not affect `valid`, such as a deprecated concept. On a process
    result whose fix paths were not all proven, this carries a notice whose `ruleId` is
    `_fixes_unproven`, as `ProcessResult.proposedFixes` describes.
    """

class ProcessResult(ValidateResult):
    """What process answers: everything validate answers, plus what an author needs to
    correct and finish the marking.

    Process is the author's call. A composer, a picker or an editor that helps someone
    write a marking calls it, often on every keystroke, and can send what was typed
    together with the facts already chosen. Beside the validate answer it carries:

    - the corrections that turn the text into canonical text, inside `recognition`;
    - what was read before repair, when repair changed it;
    - the fix paths, each a whole valid marking the engine has proven;
    - the outputs the request named in `outputs`, and only those;
    - the options for the categories the request named in `suggestFor`, only when it
      named some.

    The step-by-step trace of how the engine got here is not part of it. That is what
    explain answers, from the same request.
    """

    assertions_before_repair: Optional[List[Assertion]] = Field(default=None, alias='assertionsBeforeRepair')
    """What was read before repair: the assertions the input stated, before the repair pass
    took anything away or rewrote it. A retired concept appears under its replacement's
    name, as it does in `assertions` and in the fixes.

    Present only when repair rewrote something that was read. Absent, everything read
    came through repair. This is a record of the reading; proposed fixes are computed
    against the resulting `assertions`, never against this earlier set. Repair leaves
    author-stated rule conflicts in the resulting value for the author to resolve.

    Listed in print order, placed by the same rendering as `assertions`. A concept
    repair took away has no place in it, so it follows the others of its category.
    """
    proposed_fixes: List[Fix] = Field(alias='proposedFixes')
    """The ways to make the resulting value valid, computed from that value after applied
    changes, each a whole marking the engine has read back and found valid before
    offering it. Empty when the marking is valid, or when no change the engine could
    prove would make it so. An error's `suggestedFix` names one of these by its
    `message`.

    A request's `parts` go back in with each fix, as the caller will send them, so they
    are read again in the fix's whole and the fix is judged with them: every part that
    read as a valid part marking in the call still does, and the fix covers every part
    that does. A part that did not read as a valid part marking in the call is one no
    fix to the whole can mend, so it does not keep a fix from being offered, and it may
    still fail beside the fix.

    Proofs spend what is left of the call's work budget. When a proof runs out of it, or
    the caller cancels the call, the paths not yet proven are not offered, and
    `warnings` carries a notice whose `ruleId` is `_fixes_unproven`, so a short list or
    an empty one is not taken for every fix there is.
    """
    renders: Dict[str, Dict[str, Any]]
    """The outputs the request named in `outputs`, one entry each, keyed by output address.
    Empty when the request named none.

    A host that binds one marking to fields written in different outputs names those
    outputs and gets every one from a single call. An output that could not write the
    state is present and says so in its assessment, because an output that refused to
    write a state is a different fact from one nobody asked for.
    """
    suggestions_for: Optional[Dict[str, SuggestResult]] = Field(default=None, alias='suggestionsFor')
    """The options for each category the request named in `suggestFor`, answered against
    these settled facts exactly as `suggestForCategories` answers them, in the request's
    output format and surface.

    Computed only when asked. Present when the request named `suggestFor`, with one
    entry per category named; absent otherwise. It is how a composer keystroke gets the
    reading and the next picker's options in one round trip instead of two.
    """

class TraceEntry(_WireModel):
    """One step in the engine's explanation trace: which stage acted, what it did, and
    which concept/rule was involved.

    Lives in `ExplanationTrace.entries`. Consumers use the trace to render a "why was
    this marking produced?" breakdown. `stage` is one of `parse | repair | infer |
    validate | render`; `conceptId` and `ruleId` identify the specific element that
    drove the action.
    """

    stage: str
    """The pipeline stage that acted, such as `parse`, `normalize`, `repair`, `infer`,
    `validate`, `render`, `aggregate` or `context`. An open string.
    """
    action: str
    """What the stage did, as a short machine-readable token, such as `asserted`,
    `inferred`, `removed` or `unmatched`. An open string.
    """
    detail: str
    """A sentence describing the step for a person. It is prose and must not be parsed; the
    structured fields carry the ids.
    """
    concept_id: Optional[str] = Field(default=None, alias='conceptId')
    """The concept the step acted on, when it acted on one."""
    concept_name: Optional[str] = Field(default=None, alias='conceptName')
    """Resolved operational display for `conceptId` (the concept's rendered marking view),
    so a "why" breakdown UI can show the marking rather than the raw id. `conceptId`
    stays as the machine key.
    """
    category_id: Optional[str] = Field(default=None, alias='categoryId')
    """Category the action landed in, when the acting rule declared one. This is the
    structured channel for the category: `detail` is human-facing prose and must never
    be parsed to recover it.
    """
    rule_id: Optional[str] = Field(default=None, alias='ruleId')
    """The scheme rule that drove the step, when one did."""
    trigger_concept_ids: Optional[List[str]] = Field(default=None, alias='triggerConceptIds')
    """Concept IDs that triggered the rule producing this entry."""

class TraceRepair(_WireModel):
    """Repair recorded in an explanation trace."""

    rule_id: str = Field(alias='ruleId')
    """The id of the repair rule that fired."""
    description: str
    """What the repair does, as the scheme describes it."""
    confidence: Union[Literal['safe', 'uncertain'], str]
    """The confidence the scheme declares for the repair rule."""
    before: str
    """The text before the repair."""
    after: str
    """The text after the repair."""
    cosmetic: Optional[StrictBool] = None
    """True when the repair changed only formatting and left the assertions as they were.
    """

class TraceValidationIssue(_WireModel):
    """Validation issue recorded in an explanation trace: the constraint that failed and
    its message, and nothing else. The category, severity and concepts of the error it
    came from belong to the error, which a validate or process result reports in
    `errors`.
    """

    constraint_id: str = Field(alias='constraintId')
    """The id of the constraint that failed."""
    message: str
    """What is wrong, in words."""

class TraceInference(_WireModel):
    """Inference recorded in an explanation trace."""

    rule_id: str = Field(alias='ruleId')
    """The id of the inference rule that fired."""
    concept_id: str = Field(alias='conceptId')
    """The concept the rule added."""
    concept_name: Optional[str] = Field(default=None, alias='conceptName')
    """Resolved operational display for `conceptId` (the concept's rendered marking view),
    so a "why" breakdown UI can show the inferred marking rather than the raw id.
    `conceptId` stays as the machine key.
    """
    explanation: str
    """Why the rule added the concept, in words."""

class ExplanationTrace(_WireModel):
    """Full pipeline trace for one marking: parse input, repairs applied, inferences drawn,
    validation errors, and the final output.

    What `explain` returns, and nothing else. It takes what `process` takes and answers
    why the engine settled the marking the way it did, step by step. No other result
    carries it, because their callers want the answer rather than the working. Debug
    tools use this to explain why a marking was accepted or rejected. `repairs` lists
    each repair rule that fired and the before/after strings. `inferences` lists each
    inference rule that added a concept and the reason text.
    """

    entries: List[TraceEntry]
    """Every step the pipeline took, in the order it took them."""
    final_assertions: List[Assertion] = Field(alias='finalAssertions')
    """The assertions the pipeline settled on, listed in print order as a validate result's
    `assertions` are.
    """
    inferences: List[TraceInference]
    """Each concept an inference rule added, in the order added."""
    input: str
    """The marking text the explanation was asked for, as given."""
    rendered: str
    """The settled marking, written in the output format."""
    repairs: List[TraceRepair]
    """Each repair rule that rewrote the input, in the order applied."""
    scheme_id: str = Field(alias='schemeId')
    """The id of the scheme the marking was read against."""
    validation_errors: List[TraceValidationIssue] = Field(alias='validationErrors')
    """The constraints the settled marking violates."""

class Suggestion(_WireModel):
    """A concept offered to the user in the suggest UI, with label, description, group, and
    current selection state.

    Returned in `SuggestResult.suggestions`. `selected: true` means the concept is
    already in the current marking; clicking it again removes it. `order` controls
    display position within the group. `views` carries all render-format representations
    so the UI can switch formats without a second query. `source` distinguishes concepts
    from parsing the input (`'parse'`), preset shortcuts (`'preset'`), or alias matches
    (`'alias'`).
    """

    category_id: str = Field(alias='categoryId')
    """The category the concept belongs to."""
    concept_id: str = Field(alias='conceptId')
    """The id of the suggested concept."""
    description: str
    """Secondary label (longer name or alternate view)."""
    gated: Optional[StrictBool] = None
    """True when this concept matches the active filter but is currently gated by the
    scheme's rules (a rule prerequisite is unmet, or a constraint forbids it). Gated
    suggestions are surfaced as non-selectable, explanatory rows so the user can see why
    the concept is unavailable. Only populated when the caller passes `includeGated:
    true` and a filter is active.
    """
    group: str
    """Category label for UI grouping."""
    label: str
    """Primary display label in the current render format."""
    name: str
    """Human-readable concept name."""
    order: int
    """Sort order."""
    requires: Optional[List[str]] = None
    """When `gated` is true, the unmet prerequisite concept ids that would unlock this
    concept. Empty array when the concept is gated by a constraint with no specific
    prerequisite (e.g. mutual exclusion).
    """
    requires_display: Optional[List[str]] = Field(default=None, alias='requiresDisplay')
    """Resolved operational display (rendered marking view) for each id in `requires`,
    index-aligned, so the unlock row can read "add X first" with the marking rather than
    the raw id. `requires` stays as the machine keys.
    """
    selected: StrictBool
    """True if this concept is already in the current marking."""
    source: Optional[Union[Literal['parse', 'preset', 'alias'], str]] = None
    """`preset` on a row that offers a label preset, whose `conceptId` is `preset:`
    followed by the preset id. A concept row leaves it unset.
    """
    views: Dict[str, str]
    """All views for this concept."""

class AggregateResult(_WireModel):
    """Output of SchemeEngine.aggregate(): the combined marking produced from multiple
    portion inputs. By design aggregate always produces the proper aggregate: fixes are
    applied, never proposed. Every field it shares with `ValidateResult` means what it
    means there, `valid` included. It differs in that:

    - There is no `inputWasValid` (input is N portions, not a single string)
    - `proposedFixes` is always empty (aggregate applies what it can)
    """

    applied_fixes: List[Change] = Field(alias='appliedFixes')
    """The changes the rollup made to reach the combined marking."""
    assertions: List[Assertion]
    """The assertions of the combined marking, listed in print order as a validate result's
    are: the order the rendered marking places each concept; a concept the rendering
    leaves out appears where it would print.
    """
    display_color: Optional[ConceptColor] = Field(default=None, alias='displayColor')
    """Portable scheme-derived display color for the final post-rollup marking. Embedding
    hosts may override this presentation default.
    """
    errors: List[ValidationError]
    """The constraints the combined marking violates."""
    notices: List[Notice]
    """The notices the scheme attaches to the concepts in `assertions`, collected the same
    way `SchemeEngine.collectNotices()` collects them. Always present, empty when the
    aggregate carries none, so a consumer can read the field without checking that it
    exists.
    """
    proposed_fixes: List[Fix] = Field(alias='proposedFixes')
    """Always empty: aggregate applies every fix it can."""
    rendered: str
    """The combined marking, written in the output format."""
    valid: StrictBool
    """True when the combined marking stands once settled, as `ValidateResult.valid`
    defines it.
    """
    warnings: List[EngineWarning]
    """Advisory signals about the combined marking."""

class DiffResult(_WireModel):
    """Comparison of two assertion sets: which assertions were added, removed, or shared.
    """

    added: List[Assertion]
    """Assertions in the second marking and not the first."""
    common: List[Assertion]
    """Assertions in both markings, as the first marking holds them. Concept and category
    decide sameness; confidence, source and value are not compared.
    """
    removed: List[Assertion]
    """Assertions in the first marking and not the second."""

class ScanMatch(_WireModel):
    """A single marking found during a scheme scan of free text.

    One entry of `ScanOutcome.results` per detected marking occurrence in the document.
    `start`/`end` are offsets in UTF-16 code units in the input text, suitable for
    overlaying highlights in a rich-text editor. `result` carries what validate answers
    for the marking, so its facts and validity are available without a second call.
    `wrapped` is `true` when the marking was found inside an `embeddedMarkingStyle`
    wrapper pattern (e.g., a marking in parentheses).
    """

    end: int
    """End position in the (possibly stripped) input text"""
    inner: Optional[str] = None
    """The marking text inside the wrapper: the capture group of the scheme's
    `embeddedMarking` pattern. Present only when `wrapped` is true. Consumers that need
    to re-process the marking must use this rather than stripping delimiters from
    `marking`, because the wrapper shape is scheme-declared and is not always a pair of
    parentheses.
    """
    marking: str
    """The matched marking string (as found in the document)"""
    result: ValidateResult
    """What validate answers for this marking, read where it was found and in the role
    `role` names. A scan reads documents; it does not author them, so it carries no fix
    paths. A caller that wants to correct one region processes that region.
    """
    role: Union[Literal['whole', 'part'], str]
    """Scheme-resolved structural role of this marking: `'whole'` (a document-wide marking:
    a page-top marking, a TLP document tag) or `'part'` (a per-region marking: a
    paragraph mark, a segment, a tag).

    A marking found inside a wrapper is a part, because a scheme that declares a wrapper
    has said that is how a part is written. Otherwise, for a scheme that declares
    `render.surfaces`, it is the role recognition decides for it, the one
    `result.recognition.role` reports, and for a scheme without them, the role the
    scheme's `contextFormats` give the format it was read in. A marking with neither is
    a whole. Consumers should prefer `role` over `wrapped`, which only reflects wrapper
    syntax and not the scheme's whole/part intent.
    """
    start: int
    """Start position in the (possibly stripped) input text"""
    type: str
    """The output this marking is written in when the scan names no output format:
    `result.rendered` is written in it.

    Without `render.surfaces`, the format id that read it, or when no single format read
    it, the scheme's default output, the `defaultRenderFormat` its metadata reports.
    With them, the view it was read as, the address `result.recognition.inputFormat`
    reports, when the form it was read in is one that view writes: its `format` or a
    case's format. A marking read in one form that carries more than one surface, such
    as an attribute list, is read as no one view; when the views that name that form all
    write it under one view id, it is written in them, and its type is that bare view
    id, the output format that writes each surface in its view by that id. Any other
    marking, one read in a form its view is only read in or read as no one view, is
    written in the default for its `role`, the `defaultWholeRenderFormat` or
    `defaultPartRenderFormat` its metadata reports, and that default is its type.
    """
    wrapped: StrictBool
    """Whether the marking was found inside a wrapper pattern (e.g., parentheses)"""

class ScanLimits(_WireModel):
    """How far a scan got, and what stopped it.

    A scan spends one work budget over a whole document: finding the regions a marking
    could occupy costs against it, and so does reading each one. A document large enough
    exhausts it, and a document that offers more regions than the scanner will hold is
    capped. Either way the answer is a shorter list of markings than the document holds,
    and a shorter list is indistinguishable from a clean one unless the scanner says so.
    For a scanner whose answer decides how a document is handled, that is the difference
    between "this document carries no marking" and "this document was not read to the
    end", so it is reported rather than inferred.

    `complete` means the whole document was offered to recognition. `resource-limit`
    means the budget was spent or the caller aborted, and `limitHit` names which.
    `truncated` means the region cap was reached with budget to spare. `regionsFound` is
    how many candidate regions the scan considered, which is the number that makes a
    zero result legible.
    """

    status: Union[Literal['complete', 'truncated', 'resource-limit'], str]
    """Whether the document was read to the end, and if not, why not."""
    limit_hit: Optional[Union[Literal['aborted', 'input-length', 'transitions', 'lookups', 'live-states', 'wall-clock', 'grammar-size', 'depth'], str]] = Field(default=None, alias='limitHit')
    """The ceiling that stopped the scan, when one did."""
    regions_found: int = Field(alias='regionsFound')
    """Candidate regions the scan considered."""
    regions_capped: Optional[StrictBool] = Field(default=None, alias='regionsCapped')
    """Whether the per-document region cap was reached."""

class ScanResponseBody(_WireModel):
    """What a scan answers on the wire.

    An object rather than a bare array, because an array alone cannot tell a document
    that held no marking from a scan that stopped before the end of it. Both come back
    as zero entries, and the two mean opposite things to whoever decides what happens to
    the document next.
    """

    results: List[ScanMatch]
    """The markings the scan found, in document order."""
    limits: ScanLimits
    """How far the scan got, and what stopped it."""

class AccessRuleResult(_WireModel):
    """Result of evaluating a single qualified access rule entry."""

    activation: AccessRuleActivation
    """Machine-readable activation basis."""
    comparisons: List[AccessComparisonResult]
    """Machine-readable comparisons evaluated by the rule."""
    granted: StrictBool
    """Whether this rule passed."""
    modernized_from: Optional[List[Dict[str, Any]]] = Field(default=None, alias='modernizedFrom')
    """Deprecated-to-current concept substitutions that processing applied to the data
    before this rule was evaluated.

    Present only when the data carried a deprecated concept. It completes the
    explanation of the decision: the marking the document bears, the current concept it
    resolved to, and the comparison this rule actually made. A consumer showing why
    access was granted or denied should surface it, so the verdict is never reported
    against a concept the reader never saw.
    """
    name: str
    """Rule name from the access policy (for display)."""
    reason: Optional[str] = None
    """Denial reason from the rule definition or generated explanation."""
    rule: RuleReference
    """Qualified rule identity and semantic digest."""
    rule_index: int = Field(alias='ruleIndex')
    """Zero-based index of the rule in the access policy's evaluated rules."""
    skipped: StrictBool
    """Whether the rule was skipped because its activation did not match."""

class AccessDecision(_WireModel):
    """Overall access decision with per-rule breakdown.

    Returned by `AccessEngineAdapter.check()`. `granted` is `true` only when every
    non-skipped rule granted access. Inspect `rules` to surface per-category denial
    reasons in an authorization UI: each `AccessRuleResult` carries a human-readable
    `reason` field.
    """

    granted: StrictBool
    """True when every rule that was not skipped granted access."""
    provenance: Optional[SourceReference] = None
    """Source provenance for the access-rule source that evaluated this decision.

    Populated only when the `AccessEngine` was wired with an external `AccessRuleSource`
    override at load time (typically a `MappedAccessRuleSource` the server's Context
    loader built from an access YAML's `rules.external` block). Inline-backed decisions
    leave this field undefined to keep payloads compact for the common single-source
    case.

    Identity fields mirror the source's `sourceIdentity()` observation at
    engine-construction time.
    """
    rules: List[AccessRuleResult]
    """One result per rule in the policy, in policy order."""
    warnings: List[EngineWarning]
    """Warnings from preparing and evaluating the target, including automatic changes.
    Present on granted and denied decisions; empty when none apply.
    """

class GuideRule(_WireModel):
    """A rule in a marking guide: a data-element description with an outcome that
    contributes to the aggregate marking when activated.

    Rules are presented as checkboxes in the UI. `keywords` enables keyword-search
    filtering; `match` enables text-scan detection (e.g., finding IPv4 addresses in a
    document body). `outcome.rendered` or `outcome.concepts` provides the marking
    contribution. Rules with `when` are computed; they auto-activate based on sibling
    rule selection state and do not appear as user-visible checkboxes.

    This is the named runtime/read-result shape. Authoring input is carried by the guide
    definition's `rules.inline` entries.
    """

    category: Optional[str] = None
    """Guide category ID for grouping in the UI."""
    description: Optional[str] = None
    """Description of the data element this rule covers."""
    id: str
    """Unique identifier within the guide."""
    keywords: List[str] = Field(default_factory=list)
    """Searchable terms for literal keyword filtering (absent on computed rules)."""
    match: Optional[List[Dict[str, Any]]] = None
    """Named pattern matchers for content evaluation. Each entry is a `MatchNode`: a leaf
    spec referencing a built-in matcher (e.g. `{ type: 'ipv4' }`) or a custom regex (`{
    type: 'regex', pattern: '...' }`), or a combinator node (`any` / `all` / `not` /
    `near` / `context` / `validate`) composed over child nodes. When content is
    evaluated, both `keywords` and `match` are checked.
    """
    name: str
    """Human-readable display name."""
    outcome: Dict[str, Any]
    """What this rule contributes when active. At least one of rendered or concepts must be
    set.
    """
    overrides: Optional[List[str]] = None
    """Rule IDs whose outcomes this rule replaces when active. When omitted (default), this
    rule's outcome is additive: it contributes alongside the rules it depends on.
    """
    rationale: Optional[str] = None
    """Explanation of why this outcome applies."""
    when: Optional[Union[str, List[str], Dict[str, Any]]] = None
    """When present, this rule auto-activates based on other rules' selection state. Uses
    the same when framework as scheme rules. `has` references guide rule IDs. Rules with
    `when` are "computed"; they don't appear as checkboxes.
    """

class GuideScanSpan(_WireModel):
    """A span, by offsets into the scanned text, where a guide rule keyword or pattern
    matched.
    """

    confidence: Optional[float] = None
    """Advisory confidence in [0, 1], present only when the scan asked for it with the
    `confidence` scan option. An ordinal hint derived from the match's shape, not a
    calibrated probability.
    """
    end: int
    """Offset in the scanned text just past the end of the match, in UTF-16 code units.
    """
    keyword: str
    """The keyword that matched, or the label of the matcher that did."""
    start: int
    """Offset in the scanned text where the match starts, in UTF-16 code units."""

class GuideScanResult(_WireModel):
    """A guide rule matched by text scanning, with every span where the rule's keywords or
    matchers fired. Returned by the engine's `scanGuides` and the standalone
    `scanTextForRules` / `scanMultipleGuides` helpers.

    Parallels the scheme-side scan result: one entry per rule hit, with offsets into the
    scanned text.
    """

    guide_id: Optional[str] = Field(default=None, alias='guideId')
    """The id of the guide the rule belongs to, when the scan covered more than one."""
    matched_keywords: List[str] = Field(alias='matchedKeywords')
    """Each keyword or matcher label that fired, once each."""
    provenance: Optional[SourceReference] = None
    """Source provenance for the guide-rule source that supplied the matched rule.

    Populated only when the rule came from an external `GuideRuleSource` override wired
    into the `GuideEngine` at load time (typically a `MappedGuideRuleSource` the
    server's Context loader built from a guide YAML's `rules.external` block).
    Inline-backed results leave this field undefined to keep payloads compact for the
    common single-source case.

    Identity fields mirror the source's `sourceIdentity()` observation at
    engine-construction time.
    """
    rule: GuideRule
    """The guide rule that matched."""
    spans: List[GuideScanSpan]
    """Every place in the text where the rule fired, in the order found."""

class GuideBreakdownEntry(_WireModel):
    """Per-rule breakdown in a guide evaluation result."""

    rule: RuleReference
    """Qualified rule whose outcome was evaluated."""
    outcome: Dict[str, Any]
    """Rule outcome evaluated by the guide engine."""
    is_computed: StrictBool = Field(alias='isComputed')
    """Whether the rule was activated from other guide facts."""
    was_overridden: StrictBool = Field(alias='wasOverridden')
    """Whether an active rule replaced this rule's outcome."""
    overridden_by: Optional[RuleReference] = Field(default=None, alias='overriddenBy')
    """Qualified overriding rule when this outcome was replaced."""

class EvaluationResult(_WireModel):
    """Output of GuideEngine.evaluate(): the aggregate marking produced by evaluating a set
    of selected guide rules. Parallels SchemeEngine.process() on the scheme side.
    """

    active_computed_rules: List[GuideRule] = Field(alias='activeComputedRules')
    """The computed rules whose `when` condition the selection satisfied."""
    aggregated_marking: str = Field(alias='aggregatedMarking')
    """The effective markings rolled up into one marking by the target scheme. Empty when
    no rule contributed, or when the result spans more than one target scheme, in which
    case `aggregatedMarkings` holds one per scheme.
    """
    aggregated_markings: Optional[Dict[str, str]] = Field(default=None, alias='aggregatedMarkings')
    """Aggregated output keyed by target scheme id. Present when guide evaluation routed
    through more than one target scheme.
    """
    breakdown: List[GuideBreakdownEntry]
    """One entry per evaluated rule: for each guide, its selected rules, then its computed
    rules.
    """
    contributing_breakdown: List[GuideBreakdownEntry] = Field(alias='contributingBreakdown')
    """Subset of `breakdown` that actually contributed to `aggregatedMarking` (i.e.
    `breakdown.filter(b => !b.wasOverridden)`). Precomputed so UI layers stop
    re-filtering the full breakdown.
    """
    effective_markings: List[str] = Field(alias='effectiveMarkings')
    """The marking each contributing rule's outcome resolves to. Overridden rules
    contribute none.
    """
    guide_id: Optional[str] = Field(default=None, alias='guideId')
    """The id of the guide evaluated. Absent when the result combines several guides."""
    provenance: Optional[SourceReference] = None
    """External guide-rule source observation used by this evaluation."""
    selected_rules: List[GuideRule] = Field(alias='selectedRules')
    """The selected rules that were evaluated. Rules with a `when` condition are computed,
    not selected, and are not listed here.
    """

class CoverageReport(_WireModel):
    """Result of a coverage check. The engine is given a list of child markings and a
    single parent marking, aggregates the children in the scheme's format, then compares
    the parent with the children category by category.

    A parent can fail to cover its children in two ways, and each has its own field.
    `missing` is what the children need that the parent does not carry. `excess` is what
    the parent carries that the children do not account for. A caller tells "add this"
    from "remove this" by which field a concept is in, not by reading error text.

    How a category is judged comes from how the scheme rolls it up. A category that a
    rollup pipeline names is judged as a `pipeline` category, whatever rollup it
    declares. Every other category is judged by the rollup it declares.

    In a `union` category the parent must carry every value the children roll up to, and
    anything it lacks is missing. A value no child carries is allowed on the parent and
    is not excess.

    In an `intersection` category the parent may carry only values every child allows,
    and anything else it carries is excess. A shorter list, or none, is allowed and is
    not missing.

    In a `max`, `min` or `least_upper_bound` category the children roll up to one value,
    ordered by rank (`max`, `min`) or by the concept hierarchy (`least_upper_bound`).
    The parent must sit at or above that value for `max` and `least_upper_bound`, and at
    or below it for `min`. A parent anywhere else, including one the hierarchy does not
    order against that value, is reported once, under `missing`, and never under
    `excess`. The value reported is what the parent and children roll up to together.
    For `max` and `min` that is the children's own value. For `least_upper_bound` it is
    the bound the parent and children share, which can sit beyond the children's value,
    and it is the children's own value when the hierarchy gives them no common bound.

    In a `pipeline` category the parent covers when rolling it up with the children
    leaves it unchanged. This relies on the pipeline leaving a parent rolled up on its
    own unchanged, which the scheme author has to make true.

    The findings in `pipeline` categories are worked out for all the categories one
    pipeline names together. First they are narrowed to what the children roll up to on
    their own: a value the rollup of parent and children adds is missing only when the
    children's own rollup carries it, and a parent value that rollup drops is excess
    only when the children's own rollup does not carry it. The narrowed findings are
    then tested by acting on every finding of the report: the excess is taken out of the
    parent and the missing is put in, replacing what a single-value category held. They
    are reported only when that gives a parent that is valid under the scheme's rules
    and covers the children in every category, judged against the children's rollup.
    Otherwise, and whenever narrowing would leave nothing, the findings are not
    narrowed: every value the rollup of parent and children adds is missing, and every
    parent value it drops is excess, including one the children carry. Pipelines are
    decided one at a time, in the order the scheme lists them. Each is judged with the
    findings already decided for the pipelines before it and the full findings for those
    after it.

    In a `first` or `last` category the children roll up to one value and the rollup has
    no restrictive direction, so the parent must state that value. A parent that states
    a different one is reported once, under `missing`, as the value it should state, and
    never under `excess`. In such a category that holds several values, values the
    parent states beyond the picked one are not reported.

    In a `symmetric_difference`, `exclusive_or` or `complement` category the children
    roll up to a set and the rollup has no restrictive direction, so the parent must
    state exactly that set. Rolled-up values the parent does not state are missing.
    Values the parent states beyond that set are excess: stated, but not what the
    children roll up to. Neither side is more restrictive than the other here.

    In a category where the scheme has an `expand_group` rule, a parent that carries
    every member a group declares in that category states the group, and the group is
    not missing from it. This does not apply to a category whose rollup has no
    restrictive direction (`first`, `last`, `symmetric_difference`, `exclusive_or`,
    `complement`), where the parent must state what the children roll up to as it is.

    In a `union` or `pipeline` category the scheme marks as a hierarchy root, a parent
    value ranked at or above a needed value also covers it.

    With no non-empty children, a valid parent is covered and both lists are empty.

    `rendered` is the aggregate of the children rendered in the requested format; the UI
    can display it directly as the computed rollup without a separate aggregate()
    round-trip.
    """

    covered: StrictBool
    """Whether the parent covers the children. True when `missing` and `excess` are both
    empty and no rollup was refused. False otherwise; `missing`, `excess` and `refusals`
    together say why.
    """
    missing: List[Assertion]
    """Concepts the children need that the parent does not carry, judged per category as
    described on this type. In a `pipeline` category whose findings are not narrowed,
    this can include a value the pipeline itself adds when it rolls the parent up with
    the children. Empty when the parent lacks nothing.
    """
    missing_labels: List[str] = Field(alias='missingLabels')
    """Display labels for the concepts in `missing`, for showing to a person. A label
    appears once even when several concepts display the same way, so the list can be
    shorter than `missing` and is not aligned with it by position. Where the operation
    takes an output format, labels are spelled in it. Empty when `missing` is empty.
    """
    excess: List[Assertion]
    """Concepts the parent carries that the children do not account for, judged per
    category as described on this type. In a `symmetric_difference`, `exclusive_or` or
    `complement` category that means values the parent states beyond the set the
    children roll up to. In a `pipeline` category whose findings are not narrowed it
    means every parent value the rollup of parent and children drops, which can include
    values the children carry. Everywhere else it means values the children do not
    allow.

    Concepts appear as the author wrote them. When a written value brought others with
    it, such as a group that stands for its members, only the written value is listed,
    not the members. In a category where nothing in excess was written by the author,
    every excess value is listed. `excess` is empty only when the parent carries nothing
    the children do not account for.
    """
    excess_labels: List[str] = Field(alias='excessLabels')
    """Display labels for the concepts in `excess`, for showing to a person. A label
    appears once even when several concepts display the same way, so the list can be
    shorter than `excess` and is not aligned with it by position. Where the operation
    takes an output format, labels are spelled in it. Empty when `excess` is empty.
    """
    rendered: str
    """The children's aggregate, written in the requested format, so a UI can show the
    computed rollup without a separate aggregate call. Empty when there are no child
    markings.
    """
    refusals: Optional[List[ValidationError]] = None
    """What the scheme said when it refused a rollup this check computed, in the scheme's
    own words: the children rolled up together, or the parent rolled up with them.

    Markings that are each valid can still combine into a state the scheme does not
    allow, and that is a defect in the document rather than in the request: it is the
    answer a coverage check exists to give, so it is reported here instead of raised.
    Absent when no rollup was refused. Missing and excess concepts are never reported
    here; they have their own fields.

    Each entry names the constraint and carries the message the rule wrote, which is
    where the contributing markings are named.
    """

class ConceptDescription(_WireModel):
    """Pre-formatted tooltip content for a concept: name, definition, guidance, and
    applicable rules.
    """

    concept_id: str = Field(alias='conceptId')
    """The id of the concept described."""
    category_id: str = Field(alias='categoryId')
    """The category the concept belongs to."""
    name: str
    """The concept's display name."""
    definition: Optional[str] = None
    """What the concept means, as the scheme defines it."""
    guidance: Optional[str] = None
    """How to apply the concept, as the scheme advises."""
    rules: Optional[List[str]] = None
    """The scheme's rules that involve the concept, each as a sentence."""
    lines: List[str]
    """Pre-formatted lines for tooltip display (header, description, guidance, rules).
    """

class FilterCount(_WireModel):
    """Aggregate counts across all categories."""

    visible: int
    """Items that matched the query."""
    total: int
    """Items in every category."""

class FilterResult(_WireModel):
    """JSON-safe serialization of the engine's Set/Map-based FilterResult.

    The engine returns FilterResult with Set<string> and Map<string, ...> fields; this
    interface is what the server writes to the wire.
    """

    visible_ids: List[str] = Field(alias='visibleIds')
    """IDs of concepts or rules that matched the query."""
    category_counts: Dict[str, FilterCount] = Field(alias='categoryCounts')
    """Per-category counts."""
    total: FilterCount
    """Aggregate counts across all categories."""

class Notice(_WireModel):
    """A notice that was resolved and collected for a specific concept in a processed
    marking. Notices originate from the concept's `documentation.notices` definitions
    and may be conditional (only fire when another concept is simultaneously asserted)
    or unconditional.

    Returned by `SchemeEngine.collectNotices()`, and carried on every result that
    describes a marking, so reading the notices for a processed marking does not take a
    second call. The `required` flag indicates whether the notice represents a mandatory
    acknowledgment the UI must surface before the user can submit the marking.
    """

    concept_id: str = Field(alias='conceptId')
    """The concept the notice is attached to."""
    concept_name: str = Field(alias='conceptName')
    """The concept's display name, for showing beside the notice."""
    type: Union[Literal['warning', 'handling', 'admonition', 'distribution', 'info'], str]
    """What kind of notice this is."""
    text: str
    """The notice text the marking requires."""
    required: StrictBool
    """Whether the notice must be shown. A host surfaces a required notice before the
    marking is accepted.
    """
    views: Optional[Dict[str, str]] = None
    """The notice's own `ConceptNotice.views`, carried through unchanged.

    A host that emits a notice into a structured form needs the value the form's own
    vocabulary registers it under, and it has the collected notice rather than the
    concept it came from. Absent when the notice declares no registration at all.
    """

class SuggestResult(_WireModel):
    """What suggest answers: the concepts a picker may offer, and nothing about the marking
    itself.

    How the current marking reads and whether it stands are what validate and process
    answer, and suggest does not repeat them. A caller that wants both in one round trip
    asks process for them with `suggestFor`.
    """

    suggestions: List[Suggestion]
    """The concepts on offer, in display order."""
    warnings: List[EngineWarning]
    """Advisories raised while building the options, such as a concept source that could
    not answer in full. Empty when there were none. Advisories about the marking itself
    belong to validate and process.
    """

class RuleDescription(_WireModel):
    """Human-readable description of a guide rule. Parallels `ConceptDescription` on the
    scheme side.
    """

    rule: RuleReference
    """Qualified rule being described."""
    guide: ArtifactReference
    """Guide artifact that owns the rule."""
    name: str
    """Human-readable rule name."""
    description: Optional[str] = None
    """Optional policy-authored description."""
    outcome_text: str = Field(alias='outcomeText')
    """Human-readable outcome expression."""
    when_text: Optional[str] = Field(default=None, alias='whenText')
    """Human-readable activation expression."""
    is_computed: StrictBool = Field(alias='isComputed')
    """Whether the rule is computed from other guide facts."""
    depends_on: List[RuleReference] = Field(alias='dependsOn')
    """Qualified rules referenced by this rule's activation block."""
    overrides: List[RuleReference]
    """Qualified rules this rule overrides when it fires."""
    lines: List[str]
    """Flattened multi-line description matching `ConceptDescription.lines`."""

class AccessRuleDescription(_WireModel):
    """Human-readable description of a single access rule.

    Returned by `AccessEngineAdapter.describeAccessRule`. Tooling (LLM agents, UI
    tooltips) can render `requirementText` directly or walk `attributesNeeded` to know
    which `userAttributes` values a caller has to provide.
    """

    rule: RuleReference
    """Qualified rule being described."""
    access: ArtifactReference
    """Access artifact that owns the rule."""
    scheme: ArtifactReference
    """Scheme artifact whose assertions the rule evaluates."""
    name: str
    """Human-readable rule name."""
    description: Optional[str] = None
    """Optional policy-authored description."""
    requirement_text: str = Field(alias='requirementText')
    """Human-readable requirement expression."""
    when_text: Optional[str] = Field(default=None, alias='whenText')
    """Human-readable activation expression."""
    attributes_needed: List[str] = Field(alias='attributesNeeded')
    """Subject or context paths required to evaluate the rule."""
    depends_on: List[RuleReference] = Field(alias='dependsOn')
    """Qualified rules this rule depends on."""
    overrides: List[RuleReference]
    """Qualified rules this rule overrides."""
    lines: List[str]
    """Line-oriented rendering of the description."""

class AccessRequirementsDescription(_WireModel):
    """Aggregated immutable-policy requirements for a trusted target."""

    marking: Optional[str] = None
    """Normalized marking when the caller supplied or derived one."""
    assertions: List[Assertion]
    """Normalized effective target assertions, listed in print order: the order `marking`
    places each concept; a concept it leaves out appears where it would print.
    """
    assertion_displays: List[str] = Field(alias='assertionDisplays')
    """Resolved operational display (rendered marking view) for each entry in `assertions`,
    index-aligned. A consumer that instantiates `requirementText` against the target
    assertions substitutes this rather than the raw concept id, so the requirement
    renders the concept's marking token instead of its internal id. `assertions` keeps
    the machine `conceptId` keys.
    """
    access: ArtifactReference
    """Access artifact whose policy was described."""
    scheme: ArtifactReference
    """Scheme artifact used to normalize the target."""
    applied_rules: List[RuleReference] = Field(alias='appliedRules')
    """Qualified rules activated by the trusted target."""
    rules: List[AccessRuleDescription]
    """Per-rule immutable-policy descriptions."""
    combined_requirement_text: str = Field(alias='combinedRequirementText')
    """Combined human-readable requirement expression."""
    combined_attributes_needed: List[str] = Field(alias='combinedAttributesNeeded')
    """Union of subject and context paths needed to evaluate the target."""
    lines: List[str]
    """Line-oriented rendering of the combined description."""

class ConceptView(_WireModel):
    """Resolved view of a concept, suitable for display and adapter consumers.

    Returned by `SchemeEngineAdapter.getConceptsInCategory()`. Field names mirror the
    YAML `ConceptDoc` shape. `position` and `rank` are concrete numbers (already
    resolved from relative specs by the loader).

    `rulesReferencing` is populated by `buildSchemeView` (Handbook) and omitted by
    `getConceptsInCategory`; treat it as absent unless explicitly set.
    """

    id: str
    """Unique concept identifier."""
    name: str
    """Human-readable display name."""
    views: Dict[str, str]
    """Display representations keyed by view name; includes at least `'default'`."""
    color: Optional[ConceptColor] = None
    """Portable scheme-default display color pair, present only on concepts in the scheme's
    category-based `color_from` mode. Absent otherwise.
    """
    aliases: List[str]
    """Alternative strings that parse to this concept."""
    categories: List[str]
    """Category IDs this concept belongs to."""
    parents: List[str]
    """Broader concept IDs forming the hierarchy chain."""
    position: float
    """Resolved rendering position within a category (lower = earlier)."""
    rank: Optional[float] = None
    """Resolved severity rank for max/min rollup aggregation (higher = more severe)."""
    tier: Optional[str] = None
    """Tier label: marks this concept as a partial marking."""
    members: Optional[List[str]] = None
    """For group concepts: the member concept IDs."""
    scopes: Optional[List[str]] = None
    """Scope IDs this concept is visible in."""
    deprecated: Optional[StrictBool] = None
    """Whether this concept is deprecated."""
    deprecated_message: Optional[str] = Field(default=None, alias='deprecatedMessage')
    """Human-readable deprecation message."""
    deprecated_replacement: Optional[str] = Field(default=None, alias='deprecatedReplacement')
    """Concept ID that should be used instead of this deprecated concept."""
    definition: Optional[str] = None
    """Definition text from the concept's documentation block."""
    citation: Optional[str] = None
    """Where this concept came from: the provenance text the scheme records against it.

    Inert. Nothing in the engine reads it and no decision turns on it; it is what a
    reference surface shows when a reader asks why a concept is spelled the way it is.
    Published here because this projection is the only one a remote client can reach,
    and a scheme that makes the field mandatory had nowhere to put it.
    """
    guidance: Optional[str] = None
    """Usage guidance from the concept's documentation block."""
    notices: Optional[List[Dict[str, Any]]] = None
    """Regulatory or policy notices shown with this concept."""
    rules_referencing: Optional[List[str]] = Field(default=None, alias='rulesReferencing')
    """Human-readable summary of rules that reference this concept. Set by
    `buildSchemeView`; absent from `getConceptsInCategory`.
    """
    text_input: Optional[Dict[str, Any]] = Field(default=None, alias='textInput')
    """Text-input configuration for free-text concepts."""

class StructuralViewCategory(_WireModel):
    """StructuralViewCategory wire model."""

    id: str
    """The category id."""
    label: str
    """The category's display label."""
    items: List[Dict[str, Any]]
    """The category's concepts, in declared order."""

class StructuralView(_WireModel):
    """Render-ready Handbook tree for a scheme: its concepts grouped under the scheme's
    categories.
    """

    id: str
    """The scheme id."""
    name: str
    """The scheme's display name."""
    description: str
    """The scheme's description. Empty when the scheme declares none."""
    categories: List[StructuralViewCategory]
    """The scheme's categories in declared order, each with the concepts that belong to it.
    A category with no concepts is left out.
    """
    uncategorized: List[Dict[str, Any]]
    """Concepts that belong to none of the scheme's loaded categories. Usually empty."""
    vocabulary: Optional[Dict[str, Term]] = None
    """Display-term overrides the scheme declares, unresolved."""

class MarkingValidation(_WireModel):
    """How an audit judged one authored marking, whole or part.

    `valid` and `inputWasValid` mean exactly what `ValidateResult` defines them to mean.
    An audit asks whether the marking was right as the author wrote it, and that is
    `inputWasValid`; `valid` says whether it stands once the engine has settled it, as
    it does everywhere else.

    It carries the marking's facts and how far recognition got with it, so a caller that
    rolls markings up, checks access or offers a correction works from the audit instead
    of reading each marking a second time.
    """

    assertions: List[Assertion]
    """The facts the marking states, settled and listed in print order as a validate
    result's `assertions` are, in the role the marking has in this document.
    """
    recognition: Dict[str, Any]
    """What recognition made of the marking, as `ValidateResult.recognition`."""
    valid: StrictBool
    """Whether the marking stands once settled, as `ValidateResult.valid`."""
    input_was_valid: StrictBool = Field(alias='inputWasValid')
    """Whether the marking needed no change as written, as `ValidateResult.inputWasValid`.
    """
    errors: List[ValidationError]
    """What the scheme's rules find wrong with the settled marking."""
    proposed_fixes: List[Fix] = Field(alias='proposedFixes')
    """The ways to make the marking valid, each a whole marking the engine has read back
    and found valid, as `ProcessResult.proposedFixes`. An audit offers them because its
    caller is usually the author about to fix the document.
    """
    applied_fixes: List[Change] = Field(alias='appliedFixes')
    """Every change the engine made while settling the marking, as
    `ValidateResult.appliedFixes`. Empty when it made none, so a false `inputWasValid`
    is always explained here or in `errors`.
    """
    rendered: str
    """The settled marking, written as validate writes it when the request names no output:
    in the scheme's default format, or for a scheme that declares `render.surfaces`,
    each written surface in its default for the role the marking has in this document,
    by the rule `RenderConfigDoc.surfaces` states.
    """

class AuditWhole(_WireModel):
    """One authored document-wide marking occurrence."""

    marking: str
    """The whole marking as the document writes it."""
    start: int
    """Zero-based inclusive UTF-8 byte offset."""
    end: int
    """Zero-based exclusive UTF-8 byte offset."""
    offset_encoding: Literal['utf-8-bytes'] = Field(alias='offsetEncoding')
    """Frozen byte-offset encoding."""

class UnmarkedSpan(_WireModel):
    """A document range not governed by an authored marking."""

    start: int
    """Zero-based inclusive offset in the accepted document."""
    end: int
    """Zero-based exclusive offset in the accepted document."""
    offset_encoding: Literal['utf-8-bytes'] = Field(alias='offsetEncoding')
    """Frozen byte-offset encoding."""
    text: Optional[str] = None
    """Authored text, omitted outside the full response profile."""

class AuditPart(_WireModel):
    """One authored part marking, the region it governs, and how it was judged, facts
    included.
    """

    marking: str
    """The part marking as the document writes it."""
    text: Optional[str] = None
    """The text the part marking governs. Omitted outside the full response profile."""
    start: int
    """Zero-based inclusive UTF-8 byte offset."""
    end: int
    """Zero-based exclusive UTF-8 byte offset."""
    offset_encoding: Literal['utf-8-bytes'] = Field(alias='offsetEncoding')
    """Frozen byte-offset encoding."""
    scope_id: str = Field(alias='scopeId')
    """The scope id the part is evaluated under, `part-` followed by its one-based position
    in the document. Guide results for the part carry the same id.
    """
    validation: MarkingValidation
    """How the part marking was judged, with the facts it states."""

class Term(_WireModel):
    """A singular/plural display-word pair."""

    singular: Optional[str] = None
    """The word for one, such as `rule`."""
    plural: Optional[str] = None
    """The word for more than one, such as `rules`."""

class ReferenceSurfaceLabel(_WireModel):
    """Resolved display label for an artifact's reference-surface chrome noun: the name its
    own reference component wears (a scheme's Handbook, a guide's Guidebook, an access
    policy's Access Handbook). Always fully populated: an artifact that declares no
    override resolves to the engine's generic noun for that surface, using the same
    singular/plural `Term` contract as the artifact vocabulary. Kept as its own type
    because this is an already-resolved reference-surface value rather than the complete
    author-facing vocabulary.
    """

    singular: str
    """The noun for one, such as `Handbook`."""
    plural: str
    """The noun for more than one, such as `Handbooks`."""

class MarkingColorRule(_WireModel):
    """Ordered scheme-default or host display-color override."""

    when: Optional[Union[str, List[str], Dict[str, Any]]] = None
    """Assertion-set condition. Omit only on the final rule to create the standard
    unconditional/anything-else fallback.
    """
    color: ConceptColor
    """Complete background/text pair to use when the condition matches."""

class SchemeSummary(_WireModel):
    """Context scheme summary response."""

    id: str
    """Scheme identifier from the scheme metadata."""
    version: str
    """Scheme semantic version."""
    name: str
    """Display name from the scheme metadata."""
    description: str
    """Free-text description from the scheme metadata."""
    definition: Optional[str] = None
    """Human-readable definition of the scheme, for tooltips and about panels."""
    guidance: Optional[str] = None
    """Usage guidance for the scheme, shown in reference views."""
    color_from: Optional[str] = Field(default=None, alias='colorFrom')
    """Single-category scheme-default color source, when category mode is used."""
    color_rules: Optional[List[MarkingColorRule]] = Field(default=None, alias='colorRules')
    """Ordered rule-driven color outcomes, when rule mode is used."""
    role_aware: Optional[StrictBool] = Field(default=None, alias='roleAware')
    """Whether the scheme uses role-aware processing. Omitted when unset."""
    vocabulary: Optional[Dict[str, Term]] = None
    """Scheme-authored display vocabulary."""
    reference_surface_label: ReferenceSurfaceLabel = Field(alias='referenceSurfaceLabel')
    """Display label for this scheme's own reference component, the Handbook: the scheme's
    override or the generic "Handbook" / "Handbooks" when it declares none. Always
    populated.
    """
    context_formats: Optional[Dict[str, List[str]]] = Field(default=None, alias='contextFormats')
    """Render format IDs grouped by role. For a scheme without `render.surfaces`, the lists
    `role_detection` gives, which the scanner reads a marking's role from. For a scheme
    with them, the scanner takes the role from the view a marking was read as, and these
    lists are derived from the views for a caller that picks a format per role: each
    role lists the forms of the views that state it, `format`, case formats and
    `also_read_in` in that order, surfaces and views in declared order and each format
    once.
    """
    embedded_marking: Optional[List[Dict[str, Any]]] = Field(default=None, alias='embeddedMarking')
    """Ways a marking may appear embedded in free text. Omitted when the scheme declares
    none, which is how a client tells that inline marking is off.
    """
    default_scope: Optional[str] = Field(default=None, alias='defaultScope')
    """Default scope id applied when a marking asserts no scope explicitly. Present exactly
    when the scheme declares scopes. Pairs with the per-category `scopes` lists on the
    categories sub-resource so a remote adapter can reconstruct which categories a
    scope-only assertion set targets: the metadata the assertion-set aggregate path
    needs to render scoped categories that the whole-marking format would otherwise
    drop.
    """
    scope_label: Optional[str] = Field(default=None, alias='scopeLabel')
    """Display label for the scope selector shown in UIs. Omitted when the scheme declares
    none. Carried here so `getSchemeMeta` answers the same for a remote adapter as it
    does for a local one; without it the selector is labeled from the scheme document in
    one mode and left unlabeled in the other.
    """
    default_render_format: Optional[str] = Field(default=None, alias='defaultRenderFormat')
    """Render format applied when a call names none. A remote adapter has no way to derive
    this from the formats sub-resource: format declaration order is not default order,
    so a client that guesses the first entry renders in the wrong format whenever the
    two differ.

    Omitted when the scheme names no default. A client may then fall back to the first
    declared format, which is the same rule the engine applies, so both adapters render
    such a scheme the same way. The field is not a place to encode that absence:
    `default` is an ordinary format id, and a scheme declaring one would be
    indistinguishable from a scheme naming nothing.

    For a scheme that declares `render.surfaces`, this is the `surface/view` address of
    the view the default scope's surface writes a marking with no role in, which is its
    default for a whole.
    """
    default_part_render_format: Optional[str] = Field(default=None, alias='defaultPartRenderFormat')
    """Present only for a scheme that declares `render.surfaces`: the output address a part
    marking is written in by default. It is the `surface/view` of the default scope's
    surface's default for a part, from that surface's `default`, and does not depend on
    `contextFormats`, which lists the formats each role is read in.
    """
    default_whole_render_format: Optional[str] = Field(default=None, alias='defaultWholeRenderFormat')
    """Present only for a scheme that declares `render.surfaces`: the output address a
    whole marking is written in by default, the default scope's surface's default for a
    whole, resolved the same way `defaultPartRenderFormat` is for a part.
    """

class CategoryView(_WireModel):
    """Resolved view of a scheme category, suitable for display and selection UIs.

    Returned by `SchemeEngineAdapter.listCategories()`. Field names mirror the YAML
    `CategoryDoc` shape so consumers reading the source YAML and calling the API see
    identical names.
    """

    id: str
    """Unique category identifier."""
    label: str
    """Resolved human-readable label (always a plain string)."""
    required: Optional[StrictBool] = None
    """Whether at least one concept is required for a valid marking."""
    single: Optional[StrictBool] = None
    """Whether only one concept can be selected in this category."""
    rollup: Any
    """Rollup operator used when aggregating multiple markings."""
    sort: Optional[Union[str, List[str]]] = None
    """Sort order for concepts within this category."""
    position_overrides: Optional[Dict[str, float]] = Field(default=None, alias='positionOverrides')
    """Concept positions used only by this category's position sort."""
    scopes: Optional[List[str]] = None
    """Scope IDs this category is visible in."""
    position: Optional[float] = None
    """Declared rendering position (lower = earlier). Not resolved from array order."""
    hierarchy_root: Optional[StrictBool] = Field(default=None, alias='hierarchyRoot')
    """When true, the category grades its concepts by severity `rank`, and a coverage
    comparison counts a whole-marking concept here as covering a part's concept of equal
    or lower rank. It does not change rendering.
    """
    default_concept: Optional[Union[str, Dict[str, Any]]] = Field(default=None, alias='defaultConcept')
    """Concept ID to assert automatically when no selection exists in this category. With
    `single: true`, this provides a default level. Mirrors the scheme's
    `default_concept` for the category.
    """

class FormatView(_WireModel):
    """A format as the server describes it: what it writes and how it lays a marking out,
    not how it is built.

    A format's field tree is authoring content. It stays server-side, because the
    operations that need it (recognition, rendering, repair) are server operations, and
    a client that held the tree would be holding a second implementation of them. What a
    client legitimately needs is enough to name a format in a request, to label it in a
    picker, and to place a marking's parts itself: the resolved layout
    `RenderFormatLayout` describes, plus how the text is framed.

    The same shape whether a local engine or a remote client answers.
    """

    id: str
    """The output this entry describes, named by callers choosing an output format. For a
    scheme without `render.surfaces` it is a format id, which callers also name as an
    input format.

    For a scheme with them it is an output address, `surface/view`, and the layout
    described is the one that view's base format writes; a view with cases describes its
    base format. A view entry's `categoryOrder` and per-category maps cover only the
    categories its surface owns, so two views over one multi-surface format describe
    different category sets. A caller may also name the address as an input format, and
    `RenderConfigDoc.surfaces` says which forms that reads. Recognition reports the view
    it read the text as in `recognition.inputFormat`, the same address. These entries
    describe views; a view's forms are not entries of their own, and `contextFormats`
    lists them by role.
    """
    surface: str
    """The semantic part of a marking this entry writes, a scheme scope id: the format's
    surface, or for a scheme with `render.surfaces`, the surface this output writes.
    """
    output_view: Optional[str] = Field(default=None, alias='outputView')
    """The view part of `id`, for a scheme that declares `render.surfaces`. It holds the
    plain view id, not the percent-encoded form `id` carries. Not a concept spelling
    view; that is `view`. Absent for a scheme whose formats are its outputs.
    """
    default_for: Optional[List[Union[Literal['whole', 'part'], str]]] = Field(default=None, alias='defaultFor')
    """For a scheme that declares `render.surfaces`, the roles this view is its surface's
    default for: the roles a marking is written in this view for when a request names
    none. A surface whose `default` is one view id lists both roles on that view. A
    surface with a default per role lists `whole` on the whole's view and `part` on the
    part's, both on one view when they are the same. Empty on the surface's other views,
    so a picker filling a part field finds the part default on any surface. Absent for a
    scheme whose formats are its outputs, which has one default, `defaultRenderFormat`.
    """
    role: Optional[Union[Literal['whole', 'part'], str]] = None
    """For a scheme that declares `render.surfaces`, the role of the markings this view is
    a view of, as the view declares it. Text read as this view is a marking of this
    role. Absent for a view with no role, and for a scheme whose formats are its
    outputs.
    """
    mode: Union[Literal['inline', 'block'], str]
    """Layout: `inline` runs the fields together, `block` puts each on its own line."""
    view: Optional[str] = None
    """Default concept view for fields that do not name one."""
    prefix: Optional[str] = None
    """Written once before the nonempty whole, when it is written unconditionally."""
    suffix: Optional[str] = None
    """Written once after the nonempty whole, when it is written unconditionally."""
    separator: Optional[str] = None
    """What this format writes between two adjacent categories by default."""
    category_order: List[str] = Field(alias='categoryOrder')
    """The categories this format writes, in the order it writes them."""
    category_separators: Optional[Dict[str, str]] = Field(default=None, alias='categorySeparators')
    """What is written between two values of one category, keyed by category id. A category
    absent from the map writes its values with no separator.
    """
    separator_before: Optional[Dict[str, str]] = Field(default=None, alias='separatorBefore')
    """What is written immediately before a category, keyed by category id, with the
    format's per-boundary joins already applied. The first category in `categoryOrder`
    has nothing before it and is absent.

    The joins are resolved rather than published raw: a join names the two fields it
    sits between, and a field is a tree node a UI does not have.
    """
    category_views: Optional[Dict[str, str]] = Field(default=None, alias='categoryViews')
    """The concept view a category is written in, keyed by category id, where it differs
    from the format's own `view`.

    A field may write in a view of its own, which is how one format writes a control in
    its short spelling beside a level in its spelled-out one. A category absent from the
    map is written in the format's view.
    """
    category_tiers: Optional[Dict[str, List[Dict[str, Any]]]] = Field(default=None, alias='categoryTiers')
    """How a category's tiered concepts compose into one token, keyed by category id,
    outermost tier first.

    A concept of a lower tier does not stand beside the one it belongs to; it attaches
    to it, and what goes between them is the attachment rather than the category's own
    separator. A category absent from the map writes its values as plain values.

    The resolved `TierComposition` the scheme model already carries, not a second shape
    saying the same thing: what a surface needs here is what a field was authored with,
    and one representation is what keeps the two answers from drifting.
    """
    category_each: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, alias='categoryEach')
    """What is written around every single value of a category, keyed by category id, as
    opposed to once around all of them.

    A category whose values each carry a marker of their own is written by a field that
    declares `each`, and the marker belongs to the value rather than to the list: a
    surface placing three values with a separator between them writes the affix three
    times and the separator twice. A category absent from the map writes its values
    bare.

    Unconditional by construction. Unlike the format's own `prefix` and `suffix`, which
    are parts that may each sit behind a condition and are published only where they do
    not, `each` is two plain strings with nowhere for a condition to be written, so
    nothing here is left out.
    """
    headers: Optional[List[Dict[str, Any]]] = None
    """Headings this format writes, paired with the lists they head."""
    syntax: Optional[Dict[str, Any]] = None
    """Encoding. Absent means plain text."""

class SchemeGrammar(_WireModel):
    """Context scheme grammar response: the scheme's recognition policy.

    No separator. Every boundary belongs to the field that writes it, so there is no
    global one to publish; what is left is how a spelling found at a boundary is
    compared against the vocabulary.
    """

    case_sensitive: StrictBool = Field(alias='caseSensitive')
    """Whether the vocabulary is matched case-sensitively."""
    strip_whitespace: StrictBool = Field(alias='stripWhitespace')
    """Whether surrounding whitespace is ignored when a spelling is compared."""

class LabelPresetView(_WireModel):
    """A named shortcut marking, name only: the marking it stands for stays server-side and
    is expanded by `applyPreset`.
    """

    id: str
    """Preset id, which `applyPreset` takes."""
    label: str
    """Display label for the preset."""
    description: Optional[str] = None
    """Longer explanation of when to use the preset."""
    scope: Optional[str] = None
    """Id of the scope the preset belongs to. A preset without one belongs to the scheme's
    `defaultScope`.
    """

class SchemeScope(_WireModel):
    """One scope a scheme declares, as the scopes resource lists it."""

    id: str
    """Scope identifier, referenced by `scopes` on concepts and categories."""
    label: str
    """Display label for the scope selector."""

class DocumentAuditReport(_WireModel):
    """Authored structural and analyst-determined guide audit of one document."""

    marking_requirements: Dict[str, Any] = Field(alias='markingRequirements')
    """Evaluated canonical marking requirements, independent of discovered evidence."""
    whole: Optional[str]
    """First authored document-wide marking, or null when absent."""
    wholes: List[AuditWhole]
    """Every authored document-wide marking occurrence."""
    whole_validation: Optional[MarkingValidation] = Field(alias='wholeValidation')
    """How the first authored whole was judged, as a whole that must cover the authored
    parts that read as markings, with the facts it states. Null when the document has no
    authored whole.
    """
    parts: List[AuditPart]
    """Authored part markings and their governed regions."""
    whole_covers_parts: Optional[CoverageReport] = Field(alias='wholeCoversParts')
    """Authored whole coverage of authored parts."""
    unmarked_spans: List[UnmarkedSpan] = Field(alias='unmarkedSpans')
    """Authored ranges not governed by a marking."""
    procedural_flags: List[str] = Field(alias='proceduralFlags')
    """Stable authored-procedure findings."""
    overall_verdict: Union[Literal['pass', 'inadequate-coverage', 'procedural-gap', 'mixed'], str] = Field(alias='overallVerdict')
    """Verdict derived only from authored structural dimensions."""
    vocabulary: Optional[Dict[str, Term]]
    """Scheme-provided display vocabulary."""
    document_digest: str = Field(alias='documentDigest')
    """SHA-256 digest of the exact accepted UTF-8 document bytes."""
    guide_assessment: Optional[DocumentGuideAssessment] = Field(alias='guideAssessment')
    """Guide compilation dimension, or null when no guide applies."""
    limitations: List[AssessmentLimitation]
    """Document-level assessment limitations."""

class ContextResolution(_WireModel):
    """Resolution identity shared by every branch of one Context operation."""

    context_id: str = Field(alias='contextId')
    """Resolved Context identifier."""
    requested_version: Optional[str] = Field(default=None, alias='requestedVersion')
    """The version the request named, an alias such as `latest` included, and `latest` when
    the request named none. `resolvedVersion` is the concrete version that answered.
    Absent only from a resolution produced in process without a request.
    """
    resolved_version: str = Field(alias='resolvedVersion')
    """Concrete Context version used by the operation."""
    artifacts: List[ArtifactReference]
    """Ordered artifacts participating in the composition."""
    sources: List[SourceReference]
    """De-duplicated source observations used by the operation."""

class AssessmentLimitation(_WireModel):
    """Explains why an assessment dimension or conclusion is constrained."""

    code: str
    """Stable machine-readable limitation code."""
    scope: Optional[str] = None
    """Optional operation scope affected by the limitation."""
    reason: str
    """Human-readable explanation safe for the selected response profile."""

class ContentEvidenceSpan(_WireModel):
    """Evidence range in the exact accepted UTF-8 document bytes."""

    start: int
    """Zero-based inclusive byte offset."""
    end: int
    """Zero-based exclusive byte offset."""
    offset_encoding: Literal['utf-8-bytes'] = Field(alias='offsetEncoding')
    """Frozen offset encoding for document evidence."""
    rule: RuleReference
    """Qualified rule that produced the evidence."""
    matched: Optional[str] = None
    """Matched source text, present only in the full response profile."""

class GuideNomination(_WireModel):
    """Evidence-preserving lexical nomination requiring analyst review."""

    finding_id: str = Field(alias='findingId')
    """Deterministic identity of this evidence occurrence."""
    document_digest: str = Field(alias='documentDigest')
    """Digest of the exact scanned document bytes."""
    origin: Literal['lexical']
    """Nomination source; lexical evidence is never authoritative itself.

    Always `lexical`, and fixed for this major version. A nomination is by definition a
    rule's evidence matched in the document text, and the counts, determinations and
    advisory results that refer to nominations all mean lexical ones. A proposal from
    any other source (an analyst, an agent, a host) reaches the analyst as a manual
    selection with its own `proposalOrigin`. A new nomination source would change what
    this list means, so it would arrive as a new field, not as a new value here.
    """
    rule: RuleReference
    """Qualified rule nominated by the evidence."""
    evidence: List[ContentEvidenceSpan]
    """Evidence occurrences supporting the nomination."""
    proposed_assertions: List[AssertionReference] = Field(alias='proposedAssertions')
    """Assertions the rule would propose if accepted."""
    rationale: Optional[str] = None
    """Rule-authored explanation for the nomination."""

class GuideFindingDetermination(_WireModel):
    """Records an explicit analyst decision about one lexical nomination."""

    finding_id: str = Field(alias='findingId')
    """Stable identifier of the exact nominated occurrence."""
    document_digest: str = Field(alias='documentDigest')
    """Digest of the exact document revision reviewed."""
    decision: Annotated[Union[Literal['accepted', 'rejected'], str], _KnownOnConstruction]
    """Analyst decision for the nominated occurrence."""
    reason: str
    """Analyst-supplied reason for the decision."""
    proposal_origin: Optional[Annotated[Union[Literal['analyst-authored', 'agent-drafted', 'host-imported'], str], _KnownOnConstruction]] = Field(default=None, alias='proposalOrigin')
    """Optional provenance for how the decision proposal was drafted."""

class ManualGuideSelectionInput(_WireModel):
    """Input for an analyst-selected rule that lexical scanning missed."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    document_digest: str = Field(alias='documentDigest')
    """Digest of the exact document revision reviewed."""
    rule: RuleReference
    """Qualified loaded rule selected by the analyst."""
    evidence: List[ContentEvidenceSpan]
    """Evidence in the submitted document supporting the selection."""
    reason: str
    """Analyst-supplied reason for the selection."""
    proposal_origin: Optional[Literal['analyst-authored', 'agent-drafted', 'host-imported']] = Field(default=None, alias='proposalOrigin')
    """Optional provenance for how the selection proposal was drafted."""

class ManualGuideSelection(_WireModel):
    """Validated manual guide fact bound to a document revision."""

    document_digest: str = Field(alias='documentDigest')
    """Digest of the exact document revision reviewed."""
    rule: RuleReference
    """Qualified loaded rule selected by the analyst."""
    evidence: List[ContentEvidenceSpan]
    """Evidence in the submitted document supporting the selection."""
    reason: str
    """Analyst-supplied reason for the selection."""
    proposal_origin: Optional[Union[Literal['analyst-authored', 'agent-drafted', 'host-imported'], str]] = Field(default=None, alias='proposalOrigin')
    """Optional provenance for how the selection proposal was drafted."""
    selection_id: str = Field(alias='selectionId')
    """Deterministic selection identity."""

class GuideDeterminationInput(_WireModel):
    """Set-semantic analyst input supplied to guide evaluation."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    findings: List[GuideFindingDetermination]
    """Decisions for lexical nominations."""
    manual_selections: List[ManualGuideSelectionInput] = Field(alias='manualSelections')
    """Qualified rules manually selected by the analyst."""

class GuideFactReference(_WireModel):
    """Joins assertion support to the guide fact that supplied its authority."""

    kind: Union[Literal['accepted-finding', 'manual-selection', 'projected-finding'], str]
    """Authority state of the referenced guide fact."""
    fact_id: str = Field(alias='factId')
    """Finding or manual-selection identifier."""

class AssertionSupport(_WireModel):
    """De-duplicated content lineage for one compiled assertion."""

    support_id: str = Field(alias='supportId')
    """Content-derived stable support identifier."""
    assertion: AssertionReference
    """Assertion supported by the cited facts and rules."""
    rules: List[RuleReference]
    """Direct and computed rules contributing to the assertion."""
    evidence: List[ContentEvidenceSpan]
    """Canonically ordered evidence for the assertion."""
    fact_references: List[GuideFactReference] = Field(alias='factReferences')
    """Human-decision or projected facts supplying the assertion."""

class GuideCompiledDetail(_WireModel):
    """Full guide and scheme breakdown retained by the full response profile."""

    evaluation: EvaluationResult
    """Complete guide evaluation breakdown."""
    process: ValidateResult
    """What validate answers for the compiled assertions: the facts settled, whether they
    stand, and why not. A compiled marking is checked, not corrected, so it carries no
    fix paths.
    """

class GuideCompiledResult(_WireModel):
    """Deterministic guide compilation for one authority basis and unit."""

    assertions: List[Assertion]
    """Effective compiled assertions, listed in print order as a validate result's are.
    """
    rendered: str
    """Scheme-rendered marking for the compiled assertions."""
    valid: StrictBool
    """Whether the compiled marking stands once settled, as `ValidateResult.valid` defines
    it.
    """
    errors: List[ValidationError]
    """Validation errors from scheme processing."""
    warnings: List[EngineWarning]
    """Non-fatal scheme-processing warnings."""
    direct_rules: List[RuleReference] = Field(alias='directRules')
    """Direct rules contributing to the result."""
    computed_rules: List[RuleReference] = Field(alias='computedRules')
    """Computed rules contributing to the result."""
    overridden_rules: List[RuleReference] = Field(alias='overriddenRules')
    """Rules replaced by active overrides."""
    support_ids: List[str] = Field(alias='supportIds')
    """References into the evaluation support catalog."""
    detail: Optional[GuideCompiledDetail] = None
    """Complete evaluation and process breakdown for the full profile."""

class GuideUnitEvaluation(_WireModel):
    """Determined and projected compilation for one document unit."""

    scope_id: str = Field(alias='scopeId')
    """Opaque stable scope identifier."""
    start: int
    """Zero-based inclusive UTF-8 byte offset."""
    end: int
    """Zero-based exclusive UTF-8 byte offset."""
    offset_encoding: Literal['utf-8-bytes'] = Field(alias='offsetEncoding')
    """Frozen byte-offset encoding."""
    finding_ids: List[str] = Field(alias='findingIds')
    """Nomination IDs whose evidence belongs to this unit."""
    determined: Optional[GuideCompiledResult]
    """Compilation over accepted findings and manual selections."""
    projected: Optional[GuideCompiledResult]
    """Advisory compilation additionally assuming unresolved nominations."""

class GuideContentEvaluation(_WireModel):
    """Complete evidence and compilation result for document guide evaluation."""

    document_digest: str = Field(alias='documentDigest')
    """Digest of the exact evaluated document bytes."""
    nominations: List[GuideNomination]
    """Canonically ordered lexical nominations."""
    determinations: List[GuideFindingDetermination]
    """Validated analyst decisions."""
    manual_selections: List[ManualGuideSelection] = Field(alias='manualSelections')
    """Validated qualified manual selections."""
    unresolved_finding_ids: List[str] = Field(alias='unresolvedFindingIds')
    """Nomination IDs awaiting analyst decision."""
    accepted_finding_ids: List[str] = Field(alias='acceptedFindingIds')
    """Accepted nomination IDs."""
    rejected_finding_ids: List[str] = Field(alias='rejectedFindingIds')
    """Rejected nomination IDs."""
    support_catalog: List[AssertionSupport] = Field(alias='supportCatalog')
    """De-duplicated assertion support graph."""
    units: List[GuideUnitEvaluation]
    """Compilation results for the document and authored parts."""
    limitations: List[AssessmentLimitation]
    """Guide-dimension limitations."""

class GuideScopeCoverage(_WireModel):
    """Coverage of one unit against determined and projected requirements."""

    scope_id: str = Field(alias='scopeId')
    """Unit scope identifier."""
    determined_coverage: Optional[CoverageReport] = Field(alias='determinedCoverage')
    """Coverage against currently accepted/manual facts."""
    projected_coverage: Optional[CoverageReport] = Field(alias='projectedCoverage')
    """Advisory coverage assuming unresolved nominations are accepted."""

class DocumentGuideAssessment(_WireModel):
    """Guide dimension of a document audit."""

    status: Union[Literal['not-evaluated', 'no-findings', 'pending-determination', 'determined-sufficient', 'determined-insufficient'], str]
    """Conservative status of the determined compilation."""
    nomination_count: int = Field(alias='nominationCount')
    """Number of lexical nominations."""
    unresolved_count: int = Field(alias='unresolvedCount')
    """Number of unresolved nominations."""
    accepted_count: int = Field(alias='acceptedCount')
    """Number of accepted nominations."""
    rejected_count: int = Field(alias='rejectedCount')
    """Number of rejected nominations."""
    evidence_span_count: int = Field(alias='evidenceSpanCount')
    """Number of evidence spans."""
    evaluation: Optional[GuideContentEvaluation] = None
    """Evidence and unit detail, omitted by the summary profile."""
    unit_coverage: List[GuideScopeCoverage] = Field(alias='unitCoverage')
    """Determined/projected coverage for each evaluation unit."""
    determined_required_whole: Optional[GuideCompiledResult] = Field(alias='determinedRequiredWhole')
    """Whole-document requirement from accepted/manual facts."""
    projected_required_whole: Optional[GuideCompiledResult] = Field(alias='projectedRequiredWhole')
    """Advisory whole-document requirement including unresolved facts."""
    determined_whole_coverage: Optional[CoverageReport] = Field(alias='determinedWholeCoverage')
    """Authored whole coverage of the determined requirement."""
    projected_whole_coverage: Optional[CoverageReport] = Field(alias='projectedWholeCoverage')
    """Authored whole coverage of the projected requirement."""

class DocumentResponseCounts(_WireModel):
    """Counts the full, unprojected semantic result of a document operation."""

    nominations: int
    """Number of lexical nominations."""
    evidence_spans: int = Field(alias='evidenceSpans')
    """Number of evidence spans."""
    guide_units: int = Field(alias='guideUnits')
    """Number of evaluated guide units."""
    access_rule_results: int = Field(alias='accessRuleResults')
    """Access-rule results across all scenarios."""
    content_requirements: int = Field(alias='contentRequirements')
    """Content requirements across all scenarios."""
    context_requirements: int = Field(alias='contextRequirements')
    """Context requirements across all scenarios."""

class DocumentResponseProjection(_WireModel):
    """Describes the explicit projection applied after full evaluation."""

    profile: Union[Literal['summary', 'standard', 'full'], str]
    """Requested response detail profile."""
    details_complete: StrictBool = Field(alias='detailsComplete')
    """True only when the full profile returned every detail."""
    omitted_fields: List[str] = Field(alias='omittedFields')
    """JSON-pointer paths omitted by the selected profile."""
    counts: DocumentResponseCounts
    """Counts from the full result before projection."""

class RenderResponse(_WireModel):
    """Response body for Context rendering."""

    result: str
    """The rendered marking string."""
    assessment: Dict[str, Any]
    """What this render did to the state it was given: what was written, what was left out,
    what collapsed, what this format cannot write. Bound to this render, not to the
    format in the abstract.
    """

class NormalizeResponse(_WireModel):
    """Response body for Context normalization."""

    result: str
    """Canonical normalized form of the marking string."""

class ContextSchemeProcessResult(_WireModel):
    """Context envelope returned by scheme processing."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: ProcessResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeValidateResult(_WireModel):
    """Context envelope returned by scheme validation."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: ValidateResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeExplainResult(_WireModel):
    """Context envelope returned by a scheme explanation."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: ExplanationTrace
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeSuggestResult(_WireModel):
    """Context envelope returned by scheme suggestions."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: SuggestResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeSuggestForCategoriesResult(_WireModel):
    """Context envelope returned by per-category scheme suggestions: the options keyed by
    category id, the same map a process call returns in `suggestionsFor`.
    """

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: Dict[str, SuggestResult]
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeAggregateResult(_WireModel):
    """Context envelope returned by scheme aggregation."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: AggregateResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeScanResult(_WireModel):
    """Context envelope returned by scheme text scanning."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: ScanResponseBody
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeRenderResult(_WireModel):
    """Context envelope returned by scheme rendering."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: RenderResponse
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeNormalizeResult(_WireModel):
    """Context envelope returned by scheme normalization."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: NormalizeResponse
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeCoverageResult(_WireModel):
    """Context envelope returned by scheme coverage checks."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: CoverageReport
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeConceptDescriptionResult(_WireModel):
    """Context envelope returned by concept description."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: ConceptDescription
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeDiffResult(_WireModel):
    """Context envelope returned by scheme diff."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: DiffResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeFilterConceptsResult(_WireModel):
    """Context envelope returned by scheme concept filtering."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: FilterResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeNoticesResult(_WireModel):
    """Context envelope returned by scheme notice collection."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: List[Notice]
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextSchemeViewResult(_WireModel):
    """Context envelope returned by scheme structural view."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: StructuralView
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextGuideScanResult(_WireModel):
    """Context envelope returned by guide text scanning."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: List[GuideScanResult]
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextGuideEvaluationResult(_WireModel):
    """Context envelope returned by guide evaluation."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: EvaluationResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextGuideFilterRulesResult(_WireModel):
    """Context envelope returned by guide rule filtering."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: FilterResult
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextGuideRuleDescriptionResult(_WireModel):
    """Context envelope returned by guide-rule description."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: RuleDescription
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextGuideViewResult(_WireModel):
    """Context envelope returned by guide structural view."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: StructuralView
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextAccessDecisionResult(_WireModel):
    """Context envelope returned by trusted-target access checks."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: AccessDecision
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextAccessRequirementsResult(_WireModel):
    """Context envelope returned by immutable-policy requirement description."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: AccessRequirementsDescription
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextAccessRuleDescriptionResult(_WireModel):
    """Context envelope returned by access-rule description."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: AccessRuleDescription
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class CtxAccessRulesResponseBody(_WireModel):
    """Response body for GET /v1/ctx/{ctxId}/{version?}/access/rules: every rule in the
    context's access policy.

    One route serves both halves of the adapter contract. A caller that wants the
    descriptions has them; a caller that only wants the rule ids reads them off the same
    response instead of spending a second round trip on a projection of what it already
    holds.
    """

    rules: List[AccessRuleDescription]
    """Descriptions for every rule in the access policy, in declared order."""

class _HealthResponse(_WireModel):
    """Response body for GET /v1/health"""

    status: Literal['ok']
    """Always `"ok"` while the server is running."""
    engine_version: str = Field(alias='engineVersion')
    """Engine package version exposed to clients."""
    engine_sha: str = Field(alias='engineSha')
    """Git commit SHA of the deployed build (from GIT_SHA env var, or empty string)."""
    git_tag: str = Field(alias='gitTag')
    """Git tag of the deployed build (from GIT_TAG env var, or empty string)."""
    openapi_version: str = Field(alias='openapiVersion')
    """OpenAPI spec version from info.version in openapi.yaml. SDKs compare this against
    their vendored spec.
    """
    abi_version: Literal['v1'] = Field(alias='abiVersion')
    """Version of the wire interface this server speaks, fixed at `v1`. A client can
    compare it against the version it was built for before making calls.
    """

class _CtxListResponseBody(_WireModel):
    """Response body for GET /v1/ctx: the context ids this caller may use."""

    contexts: List[str]
    """Context ids the caller may use, sorted alphabetically."""

class _CtxVersionsResponseBody(_WireModel):
    """Response body for GET /v1/ctx/{ctxId}: versions for a given context id."""

    id: str
    """Echoed context id."""
    versions: List[str]
    """Every installed version the caller may use, sorted highest-first."""

class ContextComponent(_WireModel):
    """Component reference echoed in a `CtxDescribeResponseBody`."""

    id: str
    """Component id from the context declaration."""
    version: str
    """Requested version literal (concrete semver or 'latest')."""
    resolved_version: str = Field(alias='resolvedVersion')
    """Concrete version after `latest` resolution."""
    layers: Optional[List[ContextComponent]] = None
    """Layers nested beneath this component, in composition order."""

class ContextSchemeDescriptor(_WireModel):
    """One scheme a Context holds, and the selector that addresses it.

    Read it as a sentence: this Context holds a scheme you select with `selector`, it is
    `id` at `version`, and it plays these `roles`.

    `selector` is the whole point. A Context keys its schemes locally, and an operation
    that addresses one takes that key, so a caller that cannot enumerate the keys cannot
    reach anything but the primary. On the REST surface the same value is what
    `?scheme=` takes.
    """

    selector: str
    """Context-local key that selects this scheme."""
    id: str
    """Scheme id, from the scheme document itself."""
    version: str
    """Scheme version, from the scheme document itself."""
    roles: List[Union[Literal['primary', 'crosswalk-source', 'crosswalk-target', 'additional'], str]]
    """What this scheme is to the Context. Never empty."""

class ContextDescription(_ContextDescriptionMixin):
    """Response body for GET /v1/ctx/{ctxId}/{version}: decomposed context."""

    id: str
    """Context id."""
    version: str
    """Concrete context version after `latest` resolution."""
    description: Optional[str] = None
    """Optional human-readable description copied from the declaration."""
    scheme: ContextComponent
    """The composed scheme (base of the layer stack)."""
    schemes: List[ContextSchemeDescriptor]
    """Every scheme this Context holds, primary first, each with the selector that
    addresses it.

    The scheme sub-resources under this Context take `?scheme={selector}`, and this is
    where the valid values come from. `scheme` above answers a different question: it
    names the component the Context resolved and the layers stacked on it, which is
    provenance rather than a selector.
    """
    guides: List[ContextComponent] = Field(default_factory=list)
    """Guide components in precedence order, or omitted when none."""
    access: Optional[ContextComponent] = None
    """Access policy component, or omitted when the context defines no access doc."""
    crosswalks: List[ContextComponent] = Field(default_factory=list)
    """Crosswalk components in declaration order, or omitted when the context declares
    none. A crosswalk the context follows at `latest` reports here the concrete version
    that answered.
    """

class ContextCrosswalkTranslationResult(_WireModel):
    """Context envelope returned by a directional crosswalk translation."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: Dict[str, Any]
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""

class ContextDocumentAuditResult(_WireModel):
    """Resolved Context envelope returned by document audit operations."""

    resolution: ContextResolution
    """Single resolved composition used throughout the operation."""
    result: DocumentAuditReport
    """Typed operation result."""
    operation_limitations: List[AssessmentLimitation] = Field(alias='operationLimitations')
    """Limitations applying to the operation as a whole."""
    response_projection: Optional[DocumentResponseProjection] = Field(default=None, alias='responseProjection')
    """Projection metadata, present only for document operations."""


# Resolve postponed references after every generated declaration exists.
for _model_name in ['Attribution', 'ArtifactReference', 'SourceReference', 'RuleSourceReference', 'RuleReference', 'AssertionReference', 'AccessOperand', 'AccessComparisonResult', 'AccessRuleActivation', 'Assertion', 'ValidationError', 'EngineWarning', 'FixConceptReference', 'Fix', 'Change', 'ConceptColor', 'ValidateResult', 'ProcessResult', 'TraceEntry', 'TraceRepair', 'TraceValidationIssue', 'TraceInference', 'ExplanationTrace', 'Suggestion', 'AggregateResult', 'DiffResult', 'ScanMatch', 'ScanLimits', 'ScanResponseBody', 'AccessRuleResult', 'AccessDecision', 'GuideRule', 'GuideScanSpan', 'GuideScanResult', 'GuideBreakdownEntry', 'EvaluationResult', 'CoverageReport', 'ConceptDescription', 'FilterCount', 'FilterResult', 'Notice', 'SuggestResult', 'RuleDescription', 'AccessRuleDescription', 'AccessRequirementsDescription', 'ConceptView', 'StructuralViewCategory', 'StructuralView', 'MarkingValidation', 'AuditWhole', 'UnmarkedSpan', 'AuditPart', 'Term', 'ReferenceSurfaceLabel', 'MarkingColorRule', 'SchemeSummary', 'CategoryView', 'FormatView', 'SchemeGrammar', 'LabelPresetView', 'SchemeScope', 'DocumentAuditReport', 'ContextResolution', 'AssessmentLimitation', 'ContentEvidenceSpan', 'GuideNomination', 'GuideFindingDetermination', 'ManualGuideSelectionInput', 'ManualGuideSelection', 'GuideDeterminationInput', 'GuideFactReference', 'AssertionSupport', 'GuideCompiledDetail', 'GuideCompiledResult', 'GuideUnitEvaluation', 'GuideContentEvaluation', 'GuideScopeCoverage', 'DocumentGuideAssessment', 'DocumentResponseCounts', 'DocumentResponseProjection', 'RenderResponse', 'NormalizeResponse', 'ContextSchemeProcessResult', 'ContextSchemeValidateResult', 'ContextSchemeExplainResult', 'ContextSchemeSuggestResult', 'ContextSchemeSuggestForCategoriesResult', 'ContextSchemeAggregateResult', 'ContextSchemeScanResult', 'ContextSchemeRenderResult', 'ContextSchemeNormalizeResult', 'ContextSchemeCoverageResult', 'ContextSchemeConceptDescriptionResult', 'ContextSchemeDiffResult', 'ContextSchemeFilterConceptsResult', 'ContextSchemeNoticesResult', 'ContextSchemeViewResult', 'ContextGuideScanResult', 'ContextGuideEvaluationResult', 'ContextGuideFilterRulesResult', 'ContextGuideRuleDescriptionResult', 'ContextGuideViewResult', 'ContextAccessDecisionResult', 'ContextAccessRequirementsResult', 'ContextAccessRuleDescriptionResult', 'CtxAccessRulesResponseBody', '_HealthResponse', '_CtxListResponseBody', '_CtxVersionsResponseBody', 'ContextComponent', 'ContextSchemeDescriptor', 'ContextDescription', 'ContextCrosswalkTranslationResult', 'ContextDocumentAuditResult']:
    globals()[_model_name].model_rebuild()
del _model_name


# The contract's required members, for from_dict to check before a model
# validates a response. Generated from components.schemas; see
# _model_helpers._check_wire_shape for how a shape is read.
_WIRE_SHAPES: Dict[str, Any] = {'AccessComparisonResult': {'r': [('left', False),
                                  ('operator', False),
                                  ('right', False),
                                  ('matched', False)],
                            'p': {'left': 'AccessOperand', 'right': 'AccessOperand'}},
 'AccessDecision': {'r': [('granted', False), ('rules', False), ('warnings', False)],
                    'p': {'rules': {'i': 'AccessRuleResult'},
                          'warnings': {'i': 'Warning'},
                          'provenance': 'SourceReference'}},
 'AccessOperand': {'r': [('source', False)],
                   'p': {'assertions': {'i': 'AssertionReference'}}},
 'AccessRequirementsDescription': {'r': [('assertions', False),
                                         ('assertionDisplays', False),
                                         ('access', False),
                                         ('scheme', False),
                                         ('appliedRules', False),
                                         ('rules', False),
                                         ('combinedRequirementText', False),
                                         ('combinedAttributesNeeded', False),
                                         ('lines', False)],
                                   'p': {'assertions': {'i': 'Assertion'},
                                         'access': 'ArtifactReference',
                                         'scheme': 'ArtifactReference',
                                         'appliedRules': {'i': 'RuleReference'},
                                         'rules': {'i': 'AccessRuleDescription'}}},
 'AccessRuleActivation': {'r': [('matched', False),
                                ('assertions', False),
                                ('contextPaths', False)],
                          'p': {'assertions': {'i': 'AssertionReference'}}},
 'AccessRuleDescription': {'r': [('rule', False),
                                 ('access', False),
                                 ('scheme', False),
                                 ('name', False),
                                 ('requirementText', False),
                                 ('attributesNeeded', False),
                                 ('dependsOn', False),
                                 ('overrides', False),
                                 ('lines', False)],
                           'p': {'rule': 'RuleReference',
                                 'access': 'ArtifactReference',
                                 'scheme': 'ArtifactReference',
                                 'dependsOn': {'i': 'RuleReference'},
                                 'overrides': {'i': 'RuleReference'}}},
 'AccessRuleResult': {'r': [('ruleIndex', False),
                            ('name', False),
                            ('granted', False),
                            ('skipped', False),
                            ('activation', False),
                            ('comparisons', False),
                            ('rule', False)],
                      'p': {'activation': 'AccessRuleActivation',
                            'comparisons': {'i': 'AccessComparisonResult'},
                            'rule': 'RuleReference',
                            'modernizedFrom': {'i': 'ConceptModernization'}}},
 'AggregateResult': {'r': [('assertions', False),
                           ('rendered', False),
                           ('valid', False),
                           ('errors', False),
                           ('warnings', False),
                           ('appliedFixes', False),
                           ('proposedFixes', False),
                           ('notices', False)],
                     'p': {'assertions': {'i': 'Assertion'},
                           'displayColor': 'ConceptColor',
                           'errors': {'i': 'ValidationError'},
                           'warnings': {'i': 'Warning'},
                           'appliedFixes': {'i': 'Change'},
                           'proposedFixes': {'i': 'Fix'},
                           'notices': {'i': 'Notice'}}},
 'ArtifactReference': {'r': [('kind', False), ('id', False), ('version', False)]},
 'Assertion': {'r': [('categoryId', False),
                     ('conceptId', False),
                     ('confidence', False),
                     ('source', False)],
               'p': {'provenance': 'SourceReference'}},
 'AssertionRef': {'r': [('conceptId', False), ('categoryId', False)]},
 'AssertionReference': {'r': [('categoryId', False), ('conceptId', False)]},
 'AssertionSupport': {'r': [('supportId', False),
                            ('assertion', False),
                            ('rules', False),
                            ('evidence', False),
                            ('factReferences', False)],
                      'p': {'assertion': 'AssertionReference',
                            'rules': {'i': 'RuleReference'},
                            'evidence': {'i': 'ContentEvidenceSpan'},
                            'factReferences': {'i': 'GuideFactReference'}}},
 'AssessmentLimitation': {'r': [('code', False), ('reason', False)]},
 'Attribution': {'r': [('name', False), ('license', False)]},
 'BestEffortRuleSourceReference': {'r': [('providerId', False),
                                         ('reproducibility', False)]},
 'BestEffortSourceReference': {'r': [('attribution', False),
                                     ('providerId', False),
                                     ('reproducibility', False)],
                               'p': {'attribution': 'Attribution'}},
 'CalendarDateValueEncoding': {'r': [('type', False),
                                     ('canonical', False),
                                     ('accepts', False)]},
 'CategoryTierMap': {'v': {'i': 'TierComposition'}, 'd': []},
 'CategoryView': {'r': [('id', False), ('label', False), ('rollup', False)],
                  'p': {'defaultConcept': 'ConditionalDefaultConcept'}},
 'Change': {'r': [('ruleId', False), ('action', False), ('message', False)],
            'p': {'add': {'i': 'FixConceptReference'},
                  'remove': {'i': 'FixConceptReference'}}},
 'CharacterWindow': {'r': [('chars', False)]},
 'CheckCoverageResult': {'r': [('covered', False),
                               ('missing', False),
                               ('missingLabels', False),
                               ('excess', False),
                               ('excessLabels', False),
                               ('rendered', False)],
                         'p': {'missing': {'i': 'Assertion'},
                               'excess': {'i': 'Assertion'},
                               'refusals': {'i': 'ValidationError'}}},
 'CompositeEncodingField': {'r': [('name', False), ('type', False)]},
 'CompositeValueEncoding': {'r': [('type', False), ('fields', False)],
                            'p': {'fields': {'i': 'CompositeEncodingField'}}},
 'ConceptColor': {'r': [('background', False), ('text', False)]},
 'ConceptDescription': {'r': [('conceptId', False),
                              ('categoryId', False),
                              ('name', False),
                              ('lines', False)]},
 'ConceptModernization': {'r': [('conceptId', False),
                                ('replacedConceptId', False),
                                ('conceptDisplay', False),
                                ('replacedConceptDisplay', False)]},
 'ConceptNotice': {'r': [('type', False), ('required', False), ('text', False)]},
 'ConceptRef': {'r': [('id', False)]},
 'ConceptView': {'r': [('id', False),
                       ('name', False),
                       ('views', False),
                       ('aliases', False),
                       ('categories', False),
                       ('parents', False),
                       ('position', False)],
                 'p': {'color': 'ConceptColor',
                       'notices': {'i': 'ConceptNotice'},
                       'textInput': {'p': {'encoding': 'ValueEncoding'}}}},
 'ConditionalDefaultConcept': {'r': [('concept', False), ('when', False)],
                               'p': {'when': 'RuleWhen'}},
 'ContentEvidenceSpan': {'r': [('start', False),
                               ('end', False),
                               ('offsetEncoding', False),
                               ('rule', False)],
                         'p': {'rule': 'RuleReference'}},
 'ContextAccessDecisionResult': {'r': [('resolution', False),
                                       ('result', False),
                                       ('operationLimitations', False)],
                                 'p': {'resolution': 'ContextResolution',
                                       'result': 'AccessDecision',
                                       'operationLimitations': {'i': 'AssessmentLimitation'},
                                       'responseProjection': 'DocumentResponseProjection'}},
 'ContextAccessRequirementsResult': {'r': [('resolution', False),
                                           ('result', False),
                                           ('operationLimitations', False)],
                                     'p': {'resolution': 'ContextResolution',
                                           'result': 'AccessRequirementsDescription',
                                           'operationLimitations': {'i': 'AssessmentLimitation'},
                                           'responseProjection': 'DocumentResponseProjection'}},
 'ContextAccessRuleDescriptionResult': {'r': [('resolution', False),
                                              ('result', False),
                                              ('operationLimitations', False)],
                                        'p': {'resolution': 'ContextResolution',
                                              'result': 'AccessRuleDescription',
                                              'operationLimitations': {'i': 'AssessmentLimitation'},
                                              'responseProjection': 'DocumentResponseProjection'}},
 'ContextCrosswalkTranslationResult': {'r': [('resolution', False),
                                             ('result', False),
                                             ('operationLimitations', False)],
                                       'p': {'resolution': 'ContextResolution',
                                             'result': 'CrosswalkTranslationResult',
                                             'operationLimitations': {'i': 'AssessmentLimitation'},
                                             'responseProjection': 'DocumentResponseProjection'}},
 'ContextDocumentAuditResult': {'r': [('resolution', False),
                                      ('result', False),
                                      ('operationLimitations', False)],
                                'p': {'resolution': 'ContextResolution',
                                      'result': 'DocumentAuditReport',
                                      'operationLimitations': {'i': 'AssessmentLimitation'},
                                      'responseProjection': 'DocumentResponseProjection'}},
 'ContextGuideEvaluationResult': {'r': [('resolution', False),
                                        ('result', False),
                                        ('operationLimitations', False)],
                                  'p': {'resolution': 'ContextResolution',
                                        'result': 'EvaluationResult',
                                        'operationLimitations': {'i': 'AssessmentLimitation'},
                                        'responseProjection': 'DocumentResponseProjection'}},
 'ContextGuideFilterRulesResult': {'r': [('resolution', False),
                                         ('result', False),
                                         ('operationLimitations', False)],
                                   'p': {'resolution': 'ContextResolution',
                                         'result': 'FilterResult',
                                         'operationLimitations': {'i': 'AssessmentLimitation'},
                                         'responseProjection': 'DocumentResponseProjection'}},
 'ContextGuideRuleDescriptionResult': {'r': [('resolution', False),
                                             ('result', False),
                                             ('operationLimitations', False)],
                                       'p': {'resolution': 'ContextResolution',
                                             'result': 'RuleDescription',
                                             'operationLimitations': {'i': 'AssessmentLimitation'},
                                             'responseProjection': 'DocumentResponseProjection'}},
 'ContextGuideScanResult': {'r': [('resolution', False),
                                  ('result', False),
                                  ('operationLimitations', False)],
                            'p': {'resolution': 'ContextResolution',
                                  'result': {'i': 'GuideScanResult'},
                                  'operationLimitations': {'i': 'AssessmentLimitation'},
                                  'responseProjection': 'DocumentResponseProjection'}},
 'ContextGuideViewResult': {'r': [('resolution', False),
                                  ('result', False),
                                  ('operationLimitations', False)],
                            'p': {'resolution': 'ContextResolution',
                                  'result': 'GuideViewResponse',
                                  'operationLimitations': {'i': 'AssessmentLimitation'},
                                  'responseProjection': 'DocumentResponseProjection'}},
 'ContextResolution': {'r': [('contextId', False),
                             ('resolvedVersion', False),
                             ('artifacts', False),
                             ('sources', False)],
                       'p': {'artifacts': {'i': 'ArtifactReference'},
                             'sources': {'i': 'SourceReference'}}},
 'ContextSchemeAggregateResult': {'r': [('resolution', False),
                                        ('result', False),
                                        ('operationLimitations', False)],
                                  'p': {'resolution': 'ContextResolution',
                                        'result': 'AggregateResult',
                                        'operationLimitations': {'i': 'AssessmentLimitation'},
                                        'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeConceptDescriptionResult': {'r': [('resolution', False),
                                                 ('result', False),
                                                 ('operationLimitations', False)],
                                           'p': {'resolution': 'ContextResolution',
                                                 'result': 'ConceptDescription',
                                                 'operationLimitations': {'i': 'AssessmentLimitation'},
                                                 'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeCoverageResult': {'r': [('resolution', False),
                                       ('result', False),
                                       ('operationLimitations', False)],
                                 'p': {'resolution': 'ContextResolution',
                                       'result': 'CheckCoverageResult',
                                       'operationLimitations': {'i': 'AssessmentLimitation'},
                                       'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeDescriptor': {'r': [('selector', False),
                                   ('id', False),
                                   ('version', False),
                                   ('roles', False)]},
 'ContextSchemeDiffResult': {'r': [('resolution', False),
                                   ('result', False),
                                   ('operationLimitations', False)],
                             'p': {'resolution': 'ContextResolution',
                                   'result': 'DiffResult',
                                   'operationLimitations': {'i': 'AssessmentLimitation'},
                                   'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeExplainResult': {'r': [('resolution', False),
                                      ('result', False),
                                      ('operationLimitations', False)],
                                'p': {'resolution': 'ContextResolution',
                                      'result': 'ExplanationTrace',
                                      'operationLimitations': {'i': 'AssessmentLimitation'},
                                      'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeFilterConceptsResult': {'r': [('resolution', False),
                                             ('result', False),
                                             ('operationLimitations', False)],
                                       'p': {'resolution': 'ContextResolution',
                                             'result': 'FilterResult',
                                             'operationLimitations': {'i': 'AssessmentLimitation'},
                                             'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeNormalizeResult': {'r': [('resolution', False),
                                        ('result', False),
                                        ('operationLimitations', False)],
                                  'p': {'resolution': 'ContextResolution',
                                        'result': 'NormalizeResponse',
                                        'operationLimitations': {'i': 'AssessmentLimitation'},
                                        'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeNoticesResult': {'r': [('resolution', False),
                                      ('result', False),
                                      ('operationLimitations', False)],
                                'p': {'resolution': 'ContextResolution',
                                      'result': {'i': 'Notice'},
                                      'operationLimitations': {'i': 'AssessmentLimitation'},
                                      'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeProcessResult': {'r': [('resolution', False),
                                      ('result', False),
                                      ('operationLimitations', False)],
                                'p': {'resolution': 'ContextResolution',
                                      'result': 'ProcessResult',
                                      'operationLimitations': {'i': 'AssessmentLimitation'},
                                      'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeRenderResult': {'r': [('resolution', False),
                                     ('result', False),
                                     ('operationLimitations', False)],
                               'p': {'resolution': 'ContextResolution',
                                     'result': 'RenderResponse',
                                     'operationLimitations': {'i': 'AssessmentLimitation'},
                                     'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeScanResult': {'r': [('resolution', False),
                                   ('result', False),
                                   ('operationLimitations', False)],
                             'p': {'resolution': 'ContextResolution',
                                   'result': 'ScanResponseBody',
                                   'operationLimitations': {'i': 'AssessmentLimitation'},
                                   'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeSuggestForCategoriesResult': {'r': [('resolution', False),
                                                   ('result', False),
                                                   ('operationLimitations', False)],
                                             'p': {'resolution': 'ContextResolution',
                                                   'result': 'SuggestResultsByCategory',
                                                   'operationLimitations': {'i': 'AssessmentLimitation'},
                                                   'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeSuggestResult': {'r': [('resolution', False),
                                      ('result', False),
                                      ('operationLimitations', False)],
                                'p': {'resolution': 'ContextResolution',
                                      'result': 'SuggestResult',
                                      'operationLimitations': {'i': 'AssessmentLimitation'},
                                      'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeValidateResult': {'r': [('resolution', False),
                                       ('result', False),
                                       ('operationLimitations', False)],
                                 'p': {'resolution': 'ContextResolution',
                                       'result': 'ValidateResult',
                                       'operationLimitations': {'i': 'AssessmentLimitation'},
                                       'responseProjection': 'DocumentResponseProjection'}},
 'ContextSchemeViewResult': {'r': [('resolution', False),
                                   ('result', False),
                                   ('operationLimitations', False)],
                             'p': {'resolution': 'ContextResolution',
                                   'result': 'SchemeViewResponse',
                                   'operationLimitations': {'i': 'AssessmentLimitation'},
                                   'responseProjection': 'DocumentResponseProjection'}},
 'CrosswalkCompletedTranslationResult': {'r': [('crosswalk', False),
                                               ('outcomes', False),
                                               ('selections', False),
                                               ('source', False),
                                               ('sourceScheme', False),
                                               ('status', False),
                                               ('target', False),
                                               ('targetScheme', False)],
                                         'p': {'crosswalk': 'ArtifactReference',
                                               'sourceScheme': 'ArtifactReference',
                                               'targetScheme': 'ArtifactReference',
                                               'source': 'ValidateResult',
                                               'outcomes': {'i': 'CrosswalkOutcome'},
                                               'selections': {'i': 'CrosswalkSelectionOutcome'},
                                               'target': 'ValidateResult'}},
 'CrosswalkForbidMatch': {'u': [{'k': 'object',
                                 's': 'CrosswalkMappingForbidMatch',
                                 'c': {'kind': ['mapping']},
                                 'r': [('kind', False),
                                       ('mappingId', False),
                                       ('source', False),
                                       ('reason', False)]},
                                {'k': 'object',
                                 's': 'CrosswalkSelectionForbidMatch',
                                 'c': {'kind': ['selection-candidate']},
                                 'r': [('kind', False),
                                       ('selectionId', False),
                                       ('candidateId', False),
                                       ('sources', False),
                                       ('reason', False)]}]},
 'CrosswalkForbiddenTranslationResult': {'r': [('crosswalk', False),
                                               ('forbiddenBy', False),
                                               ('outcomes', False),
                                               ('selections', False),
                                               ('source', False),
                                               ('sourceScheme', False),
                                               ('status', False),
                                               ('targetScheme', False)],
                                         'p': {'crosswalk': 'ArtifactReference',
                                               'sourceScheme': 'ArtifactReference',
                                               'targetScheme': 'ArtifactReference',
                                               'source': 'ValidateResult',
                                               'outcomes': {'i': 'CrosswalkOutcome'},
                                               'selections': {'i': 'CrosswalkSelectionOutcome'},
                                               'forbiddenBy': {'i': 'CrosswalkForbidMatch'}}},
 'CrosswalkMappingForbidMatch': {'r': [('kind', False),
                                       ('mappingId', False),
                                       ('source', False),
                                       ('reason', False)],
                                 'p': {'source': 'AssertionReference'}},
 'CrosswalkOutcome': {'r': [('source', False),
                            ('disposition', False),
                            ('targets', False),
                            ('reason', False)],
                      'p': {'source': 'AssertionReference',
                            'targets': {'i': 'CrosswalkTarget'}}},
 'CrosswalkSelectionForbidMatch': {'r': [('kind', False),
                                         ('selectionId', False),
                                         ('candidateId', False),
                                         ('sources', False),
                                         ('reason', False)],
                                   'p': {'sources': {'i': 'AssertionReference'}}},
 'CrosswalkSelectionOutcome': {'r': [('selectionId', False),
                                     ('candidateId', False),
                                     ('disposition', False),
                                     ('targets', False),
                                     ('reason', False)],
                               'p': {'targets': {'i': 'CrosswalkTarget'}}},
 'CrosswalkTarget': {'r': [('categoryId', False), ('conceptId', False)]},
 'CrosswalkTranslationResult': {'u': [{'k': 'object',
                                       's': 'CrosswalkCompletedTranslationResult',
                                       'c': {'status': ['complete',
                                                        'partial',
                                                        'invalid-source']},
                                       'r': [('crosswalk', False),
                                             ('outcomes', False),
                                             ('selections', False),
                                             ('source', False),
                                             ('sourceScheme', False),
                                             ('status', False),
                                             ('target', False),
                                             ('targetScheme', False)]},
                                      {'k': 'object',
                                       's': 'CrosswalkForbiddenTranslationResult',
                                       'c': {'status': ['forbidden']},
                                       'r': [('crosswalk', False),
                                             ('forbiddenBy', False),
                                             ('outcomes', False),
                                             ('selections', False),
                                             ('source', False),
                                             ('sourceScheme', False),
                                             ('status', False),
                                             ('targetScheme', False)]}]},
 'CtxAccessRulesResponseBody': {'r': [('rules', False)],
                                'p': {'rules': {'i': 'AccessRuleDescription'}}},
 'CtxComponentDescriptor': {'r': [('id', False),
                                  ('version', False),
                                  ('resolvedVersion', False)],
                            'p': {'layers': {'i': 'CtxComponentDescriptor'}}},
 'CtxDescribeResponseBody': {'r': [('id', False),
                                   ('version', False),
                                   ('scheme', False),
                                   ('schemes', False)],
                             'p': {'scheme': 'CtxComponentDescriptor',
                                   'schemes': {'i': 'ContextSchemeDescriptor'},
                                   'guides': {'i': 'CtxComponentDescriptor'},
                                   'access': 'CtxComponentDescriptor',
                                   'crosswalks': {'i': 'CtxComponentDescriptor'}}},
 'CtxListResponseBody': {'r': [('contexts', False)]},
 'CtxVersionsResponseBody': {'r': [('id', False), ('versions', False)]},
 'DiffResult': {'r': [('added', False), ('removed', False), ('common', False)],
                'p': {'added': {'i': 'Assertion'},
                      'removed': {'i': 'Assertion'},
                      'common': {'i': 'Assertion'}}},
 'DocumentAuditReport': {'r': [('markingRequirements', False),
                               ('whole', True),
                               ('wholes', False),
                               ('wholeValidation', True),
                               ('parts', False),
                               ('wholeCoversParts', True),
                               ('unmarkedSpans', False),
                               ('proceduralFlags', False),
                               ('overallVerdict', False),
                               ('vocabulary', True),
                               ('documentDigest', False),
                               ('guideAssessment', True),
                               ('limitations', False)],
                         'p': {'markingRequirements': 'DocumentMarkingRequirements',
                               'wholes': {'i': 'DocumentWholeOccurrence'},
                               'wholeValidation': 'MarkingValidation',
                               'parts': {'i': 'DocumentPartAssessment'},
                               'wholeCoversParts': 'CheckCoverageResult',
                               'unmarkedSpans': {'i': 'DocumentUnmarkedSpan'},
                               'guideAssessment': 'DocumentGuideAssessment',
                               'limitations': {'i': 'AssessmentLimitation'}}},
 'DocumentGuideAssessment': {'r': [('status', False),
                                   ('nominationCount', False),
                                   ('unresolvedCount', False),
                                   ('acceptedCount', False),
                                   ('rejectedCount', False),
                                   ('evidenceSpanCount', False),
                                   ('unitCoverage', False),
                                   ('determinedRequiredWhole', True),
                                   ('projectedRequiredWhole', True),
                                   ('determinedWholeCoverage', True),
                                   ('projectedWholeCoverage', True)],
                             'p': {'evaluation': 'GuideContentEvaluation',
                                   'unitCoverage': {'i': 'GuideScopeCoverage'},
                                   'determinedRequiredWhole': 'GuideCompiledResult',
                                   'projectedRequiredWhole': 'GuideCompiledResult',
                                   'determinedWholeCoverage': 'CheckCoverageResult',
                                   'projectedWholeCoverage': 'CheckCoverageResult'}},
 'DocumentMarkingRequirements': {'r': [('whole', False), ('part', False)]},
 'DocumentPartAssessment': {'r': [('marking', False),
                                  ('start', False),
                                  ('end', False),
                                  ('offsetEncoding', False),
                                  ('scopeId', False),
                                  ('validation', False)],
                            'p': {'validation': 'MarkingValidation'}},
 'DocumentResponseCounts': {'r': [('nominations', False),
                                  ('evidenceSpans', False),
                                  ('guideUnits', False),
                                  ('accessRuleResults', False),
                                  ('contentRequirements', False),
                                  ('contextRequirements', False)]},
 'DocumentResponseProjection': {'r': [('profile', False),
                                      ('detailsComplete', False),
                                      ('omittedFields', False),
                                      ('counts', False)],
                                'p': {'counts': 'DocumentResponseCounts'}},
 'DocumentUnmarkedSpan': {'r': [('start', False),
                                ('end', False),
                                ('offsetEncoding', False)]},
 'DocumentWholeOccurrence': {'r': [('marking', False),
                                   ('start', False),
                                   ('end', False),
                                   ('offsetEncoding', False)]},
 'EmbeddedMarkingStyle': {'r': [('pattern', False), ('template', False)]},
 'EvaluationResult': {'r': [('selectedRules', False),
                            ('activeComputedRules', False),
                            ('effectiveMarkings', False),
                            ('aggregatedMarking', False),
                            ('breakdown', False),
                            ('contributingBreakdown', False)],
                      'p': {'selectedRules': {'i': 'GuideRule'},
                            'activeComputedRules': {'i': 'GuideRule'},
                            'breakdown': {'i': 'GuideBreakdownEntry'},
                            'contributingBreakdown': {'i': 'GuideBreakdownEntry'},
                            'provenance': 'SourceReference'}},
 'ExplanationTrace': {'r': [('input', False),
                            ('schemeId', False),
                            ('entries', False),
                            ('repairs', False),
                            ('validationErrors', False),
                            ('inferences', False),
                            ('finalAssertions', False),
                            ('rendered', False)],
                      'p': {'entries': {'i': 'TraceEntry'},
                            'repairs': {'i': 'TraceRepair'},
                            'validationErrors': {'i': 'TraceValidationIssue'},
                            'inferences': {'i': 'TraceInference'},
                            'finalAssertions': {'i': 'Assertion'}}},
 'FilterResult': {'r': [('visibleIds', False),
                        ('categoryCounts', False),
                        ('total', False)],
                  'p': {'categoryCounts': {'v': {'r': [('visible', False),
                                                       ('total', False)]},
                                           'd': []},
                        'total': {'r': [('visible', False), ('total', False)]}}},
 'Fix': {'r': [('message', False),
               ('rendered', False),
               ('keeps', False),
               ('adds', False),
               ('removes', False)],
         'p': {'keeps': {'i': 'FixConceptReference'},
               'adds': {'i': 'FixConceptReference'},
               'removes': {'i': 'FixConceptReference'}}},
 'FixConceptReference': {'r': [('conceptId', False), ('categoryId', False)]},
 'FormatHeaderAssociation': {'r': [('concept', False),
                                   ('headerCategory', False),
                                   ('category', False),
                                   ('position', False)]},
 'FormatSyntax': {'r': [('type', False)]},
 'FormatView': {'r': [('categoryOrder', False),
                      ('id', False),
                      ('mode', False),
                      ('surface', False)],
                'p': {'categoryTiers': 'CategoryTierMap',
                      'headers': {'i': 'FormatHeaderAssociation'},
                      'syntax': 'FormatSyntax'}},
 'GuideBreakdownEntry': {'r': [('rule', False),
                               ('outcome', False),
                               ('isComputed', False),
                               ('wasOverridden', False)],
                         'p': {'rule': 'RuleReference',
                               'outcome': 'GuideRuleOutcome',
                               'overriddenBy': 'RuleReference'}},
 'GuideCompiledDetail': {'r': [('evaluation', False), ('process', False)],
                         'p': {'evaluation': 'EvaluationResult',
                               'process': 'ValidateResult'}},
 'GuideCompiledResult': {'r': [('assertions', False),
                               ('rendered', False),
                               ('valid', False),
                               ('errors', False),
                               ('warnings', False),
                               ('directRules', False),
                               ('computedRules', False),
                               ('overriddenRules', False),
                               ('supportIds', False)],
                         'p': {'assertions': {'i': 'Assertion'},
                               'errors': {'i': 'ValidationError'},
                               'warnings': {'i': 'Warning'},
                               'directRules': {'i': 'RuleReference'},
                               'computedRules': {'i': 'RuleReference'},
                               'overriddenRules': {'i': 'RuleReference'},
                               'detail': 'GuideCompiledDetail'}},
 'GuideContentEvaluation': {'r': [('documentDigest', False),
                                  ('nominations', False),
                                  ('determinations', False),
                                  ('manualSelections', False),
                                  ('unresolvedFindingIds', False),
                                  ('acceptedFindingIds', False),
                                  ('rejectedFindingIds', False),
                                  ('supportCatalog', False),
                                  ('units', False),
                                  ('limitations', False)],
                            'p': {'nominations': {'i': 'GuideNomination'},
                                  'determinations': {'i': 'GuideFindingDetermination'},
                                  'manualSelections': {'i': 'ManualGuideSelection'},
                                  'supportCatalog': {'i': 'AssertionSupport'},
                                  'units': {'i': 'GuideUnitEvaluation'},
                                  'limitations': {'i': 'AssessmentLimitation'}}},
 'GuideDeterminationInput': {'r': [('findings', False), ('manualSelections', False)],
                             'p': {'findings': {'i': 'GuideFindingDetermination'},
                                   'manualSelections': {'i': 'ManualGuideSelectionInput'}}},
 'GuideFactReference': {'r': [('kind', False), ('factId', False)]},
 'GuideFindingDetermination': {'r': [('findingId', False),
                                     ('documentDigest', False),
                                     ('decision', False),
                                     ('reason', False)]},
 'GuideMatchSpec': {'r': [('type', False)]},
 'GuideNomination': {'r': [('findingId', False),
                           ('documentDigest', False),
                           ('origin', False),
                           ('rule', False),
                           ('evidence', False),
                           ('proposedAssertions', False)],
                     'p': {'rule': 'RuleReference',
                           'evidence': {'i': 'ContentEvidenceSpan'},
                           'proposedAssertions': {'i': 'AssertionReference'}}},
 'GuideRule': {'r': [('id', False), ('name', False), ('outcome', False)],
               'p': {'match': {'i': 'MatchNode'},
                     'outcome': 'GuideRuleOutcome',
                     'when': 'RuleWhen'}},
 'GuideRuleOutcome': {'p': {'concepts': {'i': 'ConceptRef'}}},
 'GuideRuleView': {'r': [('id', False),
                         ('name', False),
                         ('outcomeText', False),
                         ('isComputed', False),
                         ('keywords', False),
                         ('matcherLabels', False),
                         ('dependsOn', False),
                         ('dependsOnNames', False),
                         ('overrides', False),
                         ('overrideNames', False)]},
 'GuideScanResult': {'r': [('rule', False),
                           ('matchedKeywords', False),
                           ('spans', False)],
                     'p': {'rule': 'GuideRule',
                           'spans': {'i': 'GuideScanSpan'},
                           'provenance': 'SourceReference'}},
 'GuideScanSpan': {'r': [('keyword', False), ('start', False), ('end', False)]},
 'GuideScopeCoverage': {'r': [('scopeId', False),
                              ('determinedCoverage', True),
                              ('projectedCoverage', True)],
                        'p': {'determinedCoverage': 'CheckCoverageResult',
                              'projectedCoverage': 'CheckCoverageResult'}},
 'GuideUnitEvaluation': {'r': [('determined', True),
                               ('end', False),
                               ('findingIds', False),
                               ('offsetEncoding', False),
                               ('projected', True),
                               ('scopeId', False),
                               ('start', False)],
                         'p': {'determined': 'GuideCompiledResult',
                               'projected': 'GuideCompiledResult'}},
 'GuideViewResponse': {'r': [('id', False),
                             ('name', False),
                             ('description', False),
                             ('categories', False),
                             ('uncategorized', False)],
                       'p': {'categories': {'i': {'r': [('id', False),
                                                        ('label', False),
                                                        ('items', False)],
                                                  'p': {'items': {'i': 'GuideRuleView'}}}},
                             'uncategorized': {'i': 'GuideRuleView'}}},
 'HealthResponse': {'r': [('status', False),
                          ('engineVersion', False),
                          ('engineSha', False),
                          ('gitTag', False),
                          ('openapiVersion', False),
                          ('abiVersion', False)]},
 'InputSpan': {'r': [('start', False), ('end', False), ('text', False)]},
 'LabelPresetView': {'r': [('id', False), ('label', False)]},
 'ManualGuideSelection': {'r': [('documentDigest', False),
                                ('evidence', False),
                                ('reason', False),
                                ('rule', False),
                                ('selectionId', False)],
                          'p': {'rule': 'RuleReference',
                                'evidence': {'i': 'ContentEvidenceSpan'}}},
 'ManualGuideSelectionInput': {'r': [('documentDigest', False),
                                     ('rule', False),
                                     ('evidence', False),
                                     ('reason', False)],
                               'p': {'rule': 'RuleReference',
                                     'evidence': {'i': 'ContentEvidenceSpan'}}},
 'MarkingColorRule': {'r': [('color', False)],
                      'p': {'when': 'RuleWhen', 'color': 'ConceptColor'}},
 'MarkingValidation': {'r': [('assertions', False),
                             ('recognition', False),
                             ('valid', False),
                             ('inputWasValid', False),
                             ('errors', False),
                             ('proposedFixes', False),
                             ('appliedFixes', False),
                             ('rendered', False)],
                       'p': {'assertions': {'i': 'Assertion'},
                             'recognition': 'RecognitionResult',
                             'errors': {'i': 'ValidationError'},
                             'proposedFixes': {'i': 'Fix'},
                             'appliedFixes': {'i': 'Change'}}},
 'MatchAllNode': {'r': [('all', False), ('within', False)],
                  'p': {'all': {'i': 'MatchNode'}, 'within': 'Win'}},
 'MatchAnyNode': {'r': [('any', False)], 'p': {'any': {'i': 'MatchNode'}}},
 'MatchContextExpression': {'r': [('candidate', False),
                                  ('cue', False),
                                  ('within', False)],
                            'p': {'candidate': 'MatchNode',
                                  'cue': 'MatchNode',
                                  'within': 'Win'}},
 'MatchContextNode': {'r': [('context', False)],
                      'p': {'context': 'MatchContextExpression'}},
 'MatchNearExpression': {'r': [('a', False), ('b', False), ('within', False)],
                         'p': {'a': 'MatchNode', 'b': 'MatchNode', 'within': 'Win'}},
 'MatchNearNode': {'r': [('near', False)], 'p': {'near': 'MatchNearExpression'}},
 'MatchNode': {'u': [{'k': 'object', 's': 'GuideMatchSpec', 'r': [('type', False)]},
                     {'k': 'object', 's': 'MatchAnyNode', 'r': [('any', False)]},
                     {'k': 'object',
                      's': 'MatchAllNode',
                      'r': [('all', False), ('within', False)]},
                     {'k': 'object',
                      's': 'MatchNotNode',
                      'r': [('not', False), ('of', False), ('within', False)]},
                     {'k': 'object', 's': 'MatchNearNode', 'r': [('near', False)]},
                     {'k': 'object',
                      's': 'MatchContextNode',
                      'r': [('context', False)]},
                     {'k': 'object',
                      's': 'MatchValidateNode',
                      'r': [('validate', False)]}]},
 'MatchNotNode': {'r': [('not', False), ('of', False), ('within', False)],
                  'p': {'not': 'MatchNode', 'of': 'MatchNode', 'within': 'Win'}},
 'MatchValidateNode': {'r': [('validate', False)],
                       'p': {'validate': 'MatchValidationExpression'}},
 'MatchValidationExpression': {'r': [('candidate', False), ('with', False)],
                               'p': {'candidate': 'MatchNode'}},
 'NormalizeResponse': {'r': [('result', False)]},
 'Notice': {'r': [('conceptId', False),
                  ('conceptName', False),
                  ('type', False),
                  ('text', False),
                  ('required', False)]},
 'ProcessResult': {'r': [('appliedFixes', False),
                         ('assertions', False),
                         ('assessment', False),
                         ('errors', False),
                         ('inputWasValid', False),
                         ('notices', False),
                         ('proposedFixes', False),
                         ('rendered', False),
                         ('renders', False),
                         ('valid', False),
                         ('warnings', False)],
                   'p': {'assertions': {'i': 'Assertion'},
                         'errors': {'i': 'ValidationError'},
                         'warnings': {'i': 'Warning'},
                         'appliedFixes': {'i': 'Change'},
                         'assessment': 'RenderAssessment',
                         'recognition': 'RecognitionWithCorrections',
                         'notices': {'i': 'Notice'},
                         'displayColor': 'ConceptColor',
                         'assertionsBeforeRepair': {'i': 'Assertion'},
                         'proposedFixes': {'i': 'Fix'},
                         'renders': 'RenderResultsByFormat',
                         'suggestionsFor': 'SuggestResultsByCategory'}},
 'RecognitionCorrection': {'r': [('start', False),
                                 ('end', False),
                                 ('original', False),
                                 ('replacement', False),
                                 ('reason', False)]},
 'RecognitionResult': {'r': [('status', False), ('unmatched', False)],
                       'p': {'unmatched': {'i': 'InputSpan'}}},
 'RecognitionWithCorrections': {'r': [('corrections', False),
                                      ('status', False),
                                      ('unmatched', False)],
                                'p': {'unmatched': {'i': 'InputSpan'},
                                      'corrections': {'i': 'RecognitionCorrection'}}},
 'ReferenceSurfaceLabel': {'r': [('singular', False), ('plural', False)]},
 'RenderAssessment': {'r': [('emitted', False),
                            ('omitted', False),
                            ('collapsed', False),
                            ('conflicts', False),
                            ('unrepresentable', False)],
                      'p': {'emitted': {'i': 'AssertionRef'},
                            'omitted': {'i': 'AssertionRef'},
                            'collapsed': {'i': {'i': 'AssertionRef'}},
                            'conflicts': {'i': 'RenderFieldConflict'},
                            'unrepresentable': {'i': 'UnrepresentableValue'}}},
 'RenderFieldConflict': {'r': [('field', False), ('assertions', False)],
                         'p': {'assertions': {'i': 'AssertionRef'}}},
 'RenderResponse': {'r': [('result', False), ('assessment', False)],
                    'p': {'assessment': 'RenderAssessment'}},
 'RenderResult': {'r': [('rendered', False), ('assessment', False)],
                  'p': {'assessment': 'RenderAssessment'}},
 'RenderResultsByFormat': {'v': 'RenderResult', 'd': []},
 'ReproducibleRuleSourceReference': {'r': [('providerId', False),
                                           ('reproducibility', False),
                                           ('snapshotId', False)]},
 'ReproducibleSourceReference': {'r': [('attribution', False),
                                       ('providerId', False),
                                       ('reproducibility', False),
                                       ('snapshotId', False)],
                                 'p': {'attribution': 'Attribution'}},
 'RuleDescription': {'r': [('rule', False),
                           ('guide', False),
                           ('name', False),
                           ('outcomeText', False),
                           ('isComputed', False),
                           ('dependsOn', False),
                           ('overrides', False),
                           ('lines', False)],
                     'p': {'rule': 'RuleReference',
                           'guide': 'ArtifactReference',
                           'dependsOn': {'i': 'RuleReference'},
                           'overrides': {'i': 'RuleReference'}}},
 'RuleReference': {'r': [('artifact', False), ('ruleId', False), ('ruleDigest', False)],
                   'p': {'artifact': 'ArtifactReference',
                         'source': 'RuleSourceReference'}},
 'RuleSourceReference': {'u': [{'k': 'object',
                                's': 'ReproducibleRuleSourceReference',
                                'c': {'reproducibility': ['reproducible']},
                                'r': [('providerId', False),
                                      ('reproducibility', False),
                                      ('snapshotId', False)]},
                               {'k': 'object',
                                's': 'BestEffortRuleSourceReference',
                                'c': {'reproducibility': ['best-effort']},
                                'r': [('providerId', False),
                                      ('reproducibility', False)]}]},
 'RuleWhen': {'u': [{'k': 'array'},
                    {'k': 'object',
                     's': 'RuleWhenQuantifier',
                     'c': {'target': ['contributors'],
                           'quantifier': ['any', 'all', 'none']}}]},
 'RuleWhenNode': {'u': [{'k': 'object',
                         'c': {'role': ['whole', 'part'],
                               'target': ['self', 'context', 'contributors']}},
                        {'k': 'object',
                         's': 'RuleWhenQuantifier',
                         'c': {'target': ['contributors'],
                               'quantifier': ['any', 'all', 'none']}}]},
 'RuleWhenQuantifier': {'p': {'any': {'i': 'RuleWhenNode'},
                              'all': {'i': 'RuleWhenNode'},
                              'none': {'i': 'RuleWhenNode'}}},
 'ScanLimits': {'r': [('status', False), ('regionsFound', False)]},
 'ScanResponseBody': {'r': [('results', False), ('limits', False)],
                      'p': {'results': {'i': 'ScanResult'}, 'limits': 'ScanLimits'}},
 'ScanResult': {'r': [('marking', False),
                      ('start', False),
                      ('end', False),
                      ('result', False),
                      ('type', False),
                      ('wrapped', False),
                      ('role', False)],
                'p': {'result': 'ValidateResult'}},
 'SchemeGrammar': {'r': [('caseSensitive', False), ('stripWhitespace', False)]},
 'SchemeScope': {'r': [('id', False), ('label', False)]},
 'SchemeSummary': {'r': [('id', False),
                         ('version', False),
                         ('name', False),
                         ('description', False),
                         ('referenceSurfaceLabel', False)],
                   'p': {'colorRules': {'i': 'MarkingColorRule'},
                         'referenceSurfaceLabel': 'ReferenceSurfaceLabel',
                         'contextFormats': {'r': [('whole', False), ('part', False)]},
                         'embeddedMarking': {'i': 'EmbeddedMarkingStyle'}}},
 'SchemeViewResponse': {'r': [('id', False),
                              ('name', False),
                              ('description', False),
                              ('categories', False),
                              ('uncategorized', False)],
                        'p': {'categories': {'i': {'r': [('id', False),
                                                         ('label', False),
                                                         ('items', False)],
                                                   'p': {'items': {'i': 'ConceptView'}}}},
                              'uncategorized': {'i': 'ConceptView'}}},
 'SourceReference': {'u': [{'k': 'object',
                            's': 'ReproducibleSourceReference',
                            'c': {'reproducibility': ['reproducible']},
                            'r': [('attribution', False),
                                  ('providerId', False),
                                  ('reproducibility', False),
                                  ('snapshotId', False)]},
                           {'k': 'object',
                            's': 'BestEffortSourceReference',
                            'c': {'reproducibility': ['best-effort']},
                            'r': [('attribution', False),
                                  ('providerId', False),
                                  ('reproducibility', False)]}]},
 'SuggestResult': {'r': [('suggestions', False), ('warnings', False)],
                   'p': {'suggestions': {'i': 'Suggestion'},
                         'warnings': {'i': 'Warning'}}},
 'SuggestResultsByCategory': {'v': 'SuggestResult', 'd': []},
 'Suggestion': {'r': [('conceptId', False),
                      ('categoryId', False),
                      ('label', False),
                      ('description', False),
                      ('name', False),
                      ('views', False),
                      ('group', False),
                      ('selected', False),
                      ('order', False)]},
 'TextValueEncoding': {'r': [('type', False)]},
 'TierComposition': {'r': [('tier', False), ('attachedBy', False)]},
 'TokenWindow': {'r': [('tokens', False)]},
 'TraceEntry': {'r': [('stage', False), ('action', False), ('detail', False)]},
 'TraceInference': {'r': [('ruleId', False),
                          ('conceptId', False),
                          ('explanation', False)]},
 'TraceRepair': {'r': [('ruleId', False),
                       ('description', False),
                       ('confidence', False),
                       ('before', False),
                       ('after', False)]},
 'TraceValidationIssue': {'r': [('constraintId', False), ('message', False)]},
 'UnrepresentableFact': {'r': [('conceptId', False), ('reason', False)]},
 'UnrepresentableOutput': {'r': [('output', False), ('reason', False)]},
 'UnrepresentableValue': {'u': [{'k': 'object',
                                 's': 'UnrepresentableFact',
                                 'c': {'reason': ['unframable',
                                                  'reserved-literal',
                                                  'ambiguous-identity',
                                                  'no-field',
                                                  'no-view',
                                                  'value-lossy']},
                                 'r': [('conceptId', False), ('reason', False)]},
                                {'k': 'object',
                                 's': 'UnrepresentableOutput',
                                 'c': {'reason': ['unresolved-context',
                                                  'ambiguous-representation']},
                                 'r': [('output', False), ('reason', False)]}]},
 'ValidateResult': {'r': [('assertions', False),
                          ('valid', False),
                          ('inputWasValid', False),
                          ('errors', False),
                          ('warnings', False),
                          ('appliedFixes', False),
                          ('rendered', False),
                          ('assessment', False),
                          ('notices', False)],
                    'p': {'assertions': {'i': 'Assertion'},
                          'errors': {'i': 'ValidationError'},
                          'warnings': {'i': 'Warning'},
                          'appliedFixes': {'i': 'Change'},
                          'assessment': 'RenderAssessment',
                          'recognition': 'RecognitionResult',
                          'notices': {'i': 'Notice'},
                          'displayColor': 'ConceptColor'}},
 'ValidationError': {'r': [('constraintId', False), ('message', False)]},
 'ValueEncoding': {'u': [{'k': 'object',
                          's': 'TextValueEncoding',
                          'c': {'type': ['text']},
                          'r': [('type', False)]},
                         {'k': 'object',
                          's': 'CalendarDateValueEncoding',
                          'c': {'type': ['calendar-date'], 'canonical': ['YYYY-MM-DD']},
                          'r': [('type', False),
                                ('canonical', False),
                                ('accepts', False)]},
                         {'k': 'object',
                          's': 'CompositeValueEncoding',
                          'c': {'type': ['composite']},
                          'r': [('type', False), ('fields', False)]}]},
 'Warning': {'r': [('kind', False), ('message', False)]},
 'Win': {'u': [{'k': 'object', 's': 'TokenWindow', 'r': [('tokens', False)]},
               {'k': 'object', 's': 'CharacterWindow', 'r': [('chars', False)]}]}}

# The OpenAPI component each public model is generated from, where
# it has one. A component that requires nothing has no table entry.
_MODEL_SHAPES: Dict[str, str] = {
    'Attribution': 'Attribution',
    'ArtifactReference': 'ArtifactReference',
    'SourceReference': 'SourceReference',
    'RuleSourceReference': 'RuleSourceReference',
    'RuleReference': 'RuleReference',
    'AssertionReference': 'AssertionReference',
    'AccessOperand': 'AccessOperand',
    'AccessComparisonResult': 'AccessComparisonResult',
    'AccessRuleActivation': 'AccessRuleActivation',
    'Assertion': 'Assertion',
    'ValidationError': 'ValidationError',
    'EngineWarning': 'Warning',
    'FixConceptReference': 'FixConceptReference',
    'Fix': 'Fix',
    'Change': 'Change',
    'ConceptColor': 'ConceptColor',
    'ValidateResult': 'ValidateResult',
    'ProcessResult': 'ProcessResult',
    'TraceEntry': 'TraceEntry',
    'TraceRepair': 'TraceRepair',
    'TraceValidationIssue': 'TraceValidationIssue',
    'TraceInference': 'TraceInference',
    'ExplanationTrace': 'ExplanationTrace',
    'Suggestion': 'Suggestion',
    'AggregateResult': 'AggregateResult',
    'DiffResult': 'DiffResult',
    'ScanMatch': 'ScanResult',
    'ScanLimits': 'ScanLimits',
    'ScanResponseBody': 'ScanResponseBody',
    'AccessRuleResult': 'AccessRuleResult',
    'AccessDecision': 'AccessDecision',
    'GuideRule': 'GuideRule',
    'GuideScanSpan': 'GuideScanSpan',
    'GuideScanResult': 'GuideScanResult',
    'GuideBreakdownEntry': 'GuideBreakdownEntry',
    'EvaluationResult': 'EvaluationResult',
    'CoverageReport': 'CheckCoverageResult',
    'ConceptDescription': 'ConceptDescription',
    'FilterResult': 'FilterResult',
    'Notice': 'Notice',
    'SuggestResult': 'SuggestResult',
    'RuleDescription': 'RuleDescription',
    'AccessRuleDescription': 'AccessRuleDescription',
    'AccessRequirementsDescription': 'AccessRequirementsDescription',
    'ConceptView': 'ConceptView',
    'StructuralView': 'SchemeViewResponse',
    'MarkingValidation': 'MarkingValidation',
    'UnmarkedSpan': 'DocumentUnmarkedSpan',
    'Term': 'Term',
    'ReferenceSurfaceLabel': 'ReferenceSurfaceLabel',
    'MarkingColorRule': 'MarkingColorRule',
    'SchemeSummary': 'SchemeSummary',
    'CategoryView': 'CategoryView',
    'FormatView': 'FormatView',
    'SchemeGrammar': 'SchemeGrammar',
    'LabelPresetView': 'LabelPresetView',
    'SchemeScope': 'SchemeScope',
    'DocumentAuditReport': 'DocumentAuditReport',
    'ContextResolution': 'ContextResolution',
    'AssessmentLimitation': 'AssessmentLimitation',
    'ContentEvidenceSpan': 'ContentEvidenceSpan',
    'GuideNomination': 'GuideNomination',
    'GuideFindingDetermination': 'GuideFindingDetermination',
    'ManualGuideSelectionInput': 'ManualGuideSelectionInput',
    'ManualGuideSelection': 'ManualGuideSelection',
    'GuideDeterminationInput': 'GuideDeterminationInput',
    'GuideFactReference': 'GuideFactReference',
    'AssertionSupport': 'AssertionSupport',
    'GuideCompiledDetail': 'GuideCompiledDetail',
    'GuideCompiledResult': 'GuideCompiledResult',
    'GuideUnitEvaluation': 'GuideUnitEvaluation',
    'GuideContentEvaluation': 'GuideContentEvaluation',
    'GuideScopeCoverage': 'GuideScopeCoverage',
    'DocumentGuideAssessment': 'DocumentGuideAssessment',
    'DocumentResponseCounts': 'DocumentResponseCounts',
    'DocumentResponseProjection': 'DocumentResponseProjection',
    'RenderResponse': 'RenderResponse',
    'NormalizeResponse': 'NormalizeResponse',
    'ContextSchemeProcessResult': 'ContextSchemeProcessResult',
    'ContextSchemeValidateResult': 'ContextSchemeValidateResult',
    'ContextSchemeExplainResult': 'ContextSchemeExplainResult',
    'ContextSchemeSuggestResult': 'ContextSchemeSuggestResult',
    'ContextSchemeSuggestForCategoriesResult': 'ContextSchemeSuggestForCategoriesResult',
    'ContextSchemeAggregateResult': 'ContextSchemeAggregateResult',
    'ContextSchemeScanResult': 'ContextSchemeScanResult',
    'ContextSchemeRenderResult': 'ContextSchemeRenderResult',
    'ContextSchemeNormalizeResult': 'ContextSchemeNormalizeResult',
    'ContextSchemeCoverageResult': 'ContextSchemeCoverageResult',
    'ContextSchemeConceptDescriptionResult': 'ContextSchemeConceptDescriptionResult',
    'ContextSchemeDiffResult': 'ContextSchemeDiffResult',
    'ContextSchemeFilterConceptsResult': 'ContextSchemeFilterConceptsResult',
    'ContextSchemeNoticesResult': 'ContextSchemeNoticesResult',
    'ContextSchemeViewResult': 'ContextSchemeViewResult',
    'ContextGuideScanResult': 'ContextGuideScanResult',
    'ContextGuideEvaluationResult': 'ContextGuideEvaluationResult',
    'ContextGuideFilterRulesResult': 'ContextGuideFilterRulesResult',
    'ContextGuideRuleDescriptionResult': 'ContextGuideRuleDescriptionResult',
    'ContextGuideViewResult': 'ContextGuideViewResult',
    'ContextAccessDecisionResult': 'ContextAccessDecisionResult',
    'ContextAccessRequirementsResult': 'ContextAccessRequirementsResult',
    'ContextAccessRuleDescriptionResult': 'ContextAccessRuleDescriptionResult',
    'CtxAccessRulesResponseBody': 'CtxAccessRulesResponseBody',
    '_HealthResponse': 'HealthResponse',
    '_CtxListResponseBody': 'CtxListResponseBody',
    '_CtxVersionsResponseBody': 'CtxVersionsResponseBody',
    'ContextComponent': 'CtxComponentDescriptor',
    'ContextSchemeDescriptor': 'ContextSchemeDescriptor',
    'ContextDescription': 'CtxDescribeResponseBody',
    'ContextCrosswalkTranslationResult': 'ContextCrosswalkTranslationResult',
    'ContextDocumentAuditResult': 'ContextDocumentAuditResult',
}
