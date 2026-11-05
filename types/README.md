# ezclassify-contract

Pydantic wire and domain contracts for the EzClassify REST Python SDK.

## Installation

```bash
pip install ezclassify-contract
```

## What's included

- **Pydantic models** for all REST result types (`ValidateResult`,
  `ProcessResult`, `ExplanationTrace`, `AggregateResult`, `DiffResult`,
  `ScanMatch`, `Suggestion`, `Assertion`, etc.)

## Reading and building models

Every model reads a server response the forgiving way: a field the server adds
in a later release is ignored, so an older SDK keeps decoding newer responses.
`from_dict` and `model_validate` both work like this.

`from_dict` is also strict about what the contract requires. A member the
OpenAPI document marks required has to be present, at any depth, and may be
null only where the contract allows null; otherwise `from_dict` raises
`pydantic.ValidationError` whose `loc` names the member, such as
`("result", "assessment", "omitted")`. That holds inside the members kept as
plain dictionaries too. A default a model declares for a required member, such
as `Assertion.source`, applies when you build one with keywords, never when
`from_dict` decodes a response. `model_validate` is Pydantic's structural
check and does not look for these members.

`Assertion` is different because you also build it yourself, for example to
pass assertions to an access check. Building one with keywords refuses a
keyword the model does not declare, so a typo fails at once instead of
silently dropping the value before the request is sent:

```python
from ezclassify_contract import Assertion

Assertion(category_id="level", concept_id="LOW", expires_at="2027-01-01")  # ok
Assertion(
    category_id="level", concept_id="LOW", expiresat="2027-01-01"
)  # ValidationError
```

That check covers keyword construction only. `Assertion.model_validate(...)`
and `Assertion.from_dict(...)` treat their input as wire data and ignore keys
they do not know, so a misspelled key in a dictionary is dropped without an
error. When you build assertions from your own configuration, unpack it into
the constructor (`Assertion(**config)`) so a misspelled key is caught. The same
applies to `model_copy(update=...)`, which does not validate its keys.

If you type-check with the Pydantic mypy plugin, setting `init_forbid_extra = true`
under `[tool.pydantic-mypy]` catches the same typo before the code runs.

## How the models are maintained

`models.py` is generated from the OpenAPI components and JSON Schemas the
[ezclassify/contracts](https://github.com/ezclassify/contracts) repository publishes, so the models in the wheel match the
wire contract the runtime answers with. Handwritten Python ergonomics and
cross-field validation are isolated in `_model_helpers.py`.

## Dependencies

- `pydantic>=2.14.1,<3`
- `typing-extensions>=4.15`

[`pyproject.toml`](pyproject.toml) is authoritative for dependency requirements.
