"""Reading a declared shape out of a model's answer.

The capability, with no idea what it is reading. A caller hands over images
and a Pydantic model; what comes back is an instance of that model or an
:class:`LlmContractError` naming what the model got wrong. Nothing here knows
about expiry dates, serial numbers or ISBNs — which is the point: the same
code serves a food label, an equipment nameplate and a book's copyright page,
and none of those words appear in this file.

Three parts, kept apart because they fail differently:

* :func:`unwrap_object` — models wrap their answer in a list, or under a key
  of their own invention. That is untidiness, not error, and is normalised.
* :func:`describe_validation_error` — an answer of the right shape carrying
  the wrong values. Every field on an extraction schema is optional, so what
  fails is a weaker model writing ``"weight_value": "about 500 g"``; the only
  way to see that is to quote it back.
* :func:`parse_into` — the two above plus JSON reading, as the single
  ``validate`` callable :func:`app.core.llm.json_retry.complete_json` expects.
"""

from __future__ import annotations

import json
from collections.abc import Container
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.llm.errors import LlmContractError
from app.core.llm.json_parsing import extract_json

__all__ = [
    'build_shape_prompt',
    'describe_validation_error',
    'parse_into',
    'read_json',
    'unwrap_object',
]

# How much of a value the model sent survives into the error message. Enough
# to recognise what went wrong, short enough that a rambling answer does not
# become the error.
_VALUE_PREVIEW = 60


def read_json(content: str) -> Any:
    """Core's parser, with "not JSON at all" folded into the contract error.

    :func:`extract_json` reports an unparseable answer as
    ``json.JSONDecodeError`` because at that layer it is a fact about a
    string. Here it is one of several ways the model can fail its side of the
    deal, and callers — the retry loop, the router — should only have to know
    about one of them.
    """
    try:
        return extract_json(content)
    except json.JSONDecodeError as err:
        preview = content.strip()[:_VALUE_PREVIEW]
        raise LlmContractError(
            f'LLM did not return JSON. Answer began: {preview!r}'
        ) from err


def unwrap_object(data: Any, known_fields: Container[str] = ()) -> dict[str, Any]:
    """Normalise the wrappers a model puts around a single object.

      {"name": ...}                  -> direct (OK)
      [{"name": ...}]                -> list with first element
      [{"product": {"name": ...}}]   -> nested wrapper
      {"data": [{"name": ...}]}      -> dict with list value
      {"product": {"name": ...}}     -> single-key dict wrapper

    A single-key dict is only unwrapped when its value is itself an object or
    a list — a schema whose one field happens to be filled must survive.

    *known_fields* is the last guard, and it is not optional in practice: once
    a schema gained a nested field, an answer that filled only that field
    (``{"nutrition": {...}}``) looked exactly like an envelope, and unwrapping
    it threw the answer away and returned an object of nulls. A key the schema
    declares is never an envelope.
    """
    if isinstance(data, list):
        if len(data) == 0:
            raise LlmContractError('LLM returned an empty list')
        data = data[0]
    elif isinstance(data, dict) and len(data) == 1:
        only_key = next(iter(data))
        only_val = data[only_key]
        if only_key in known_fields:
            pass
        elif isinstance(only_val, list):
            if len(only_val) == 0:
                raise LlmContractError(
                    f'LLM returned empty list under key "{only_key}"'
                )
            data = only_val[0]
        elif isinstance(only_val, dict):
            data = only_val

    if not isinstance(data, dict):
        raise LlmContractError(
            f'LLM response is not a dict after unwrap: {type(data).__name__}'
        )
    return data


def describe_validation_error(err: ValidationError) -> str:
    """Name each field the model got wrong and what it sent instead."""
    parts = []
    for detail in err.errors():
        field = '.'.join(str(p) for p in detail['loc']) or '(root)'
        value = repr(detail.get('input'))
        if len(value) > _VALUE_PREVIEW:
            value = value[:_VALUE_PREVIEW] + '…'
        parts.append(f'{field}={value} ({detail["msg"]})')
    return 'LLM returned values that do not fit the schema: ' + '; '.join(parts)


def parse_into[T: BaseModel](schema: type[T], content: str) -> T:
    """Read *content* as an instance of *schema*, or raise ``LlmContractError``."""
    data = unwrap_object(read_json(content), known_fields=schema.model_fields)
    try:
        return schema(**data)
    except ValidationError as err:
        raise LlmContractError(describe_validation_error(err)) from err


def build_shape_prompt(schema: type[BaseModel]) -> str:
    """Spell out the answer's shape from the schema itself.

    Providers that enforce ``json_schema`` server-side make this redundant;
    the ones that ignore it are exactly the ones that need telling. Rendering
    from ``model_json_schema()`` rather than a hand-written block means a
    field added to the model cannot be forgotten in the prompt — the two used
    to be separate lists in vision, and drifted.
    """
    properties: dict[str, Any] = schema.model_json_schema().get('properties', {})
    lines = [f'  "{name}": {_render_field(spec)}' for name, spec in properties.items()]
    body = ',\n'.join(lines)
    return (
        'Respond with JSON only — no prose, no markdown fence — using exactly '
        f'these keys. Use null for anything not visible.\n{{\n{body}\n}}'
    )


def _render_field(spec: dict[str, Any]) -> str:
    """One field as "<type> — <description>", both taken from the schema."""
    rendered = _render_type(spec)
    description = spec.get('description')
    return f'{rendered}  // {description}' if description else rendered


def _render_type(spec: dict[str, Any]) -> str:
    """The JSON type of a field, seeing through Pydantic's optional unions."""
    if 'anyOf' in spec:
        named = [
            _render_type(option)
            for option in spec['anyOf']
            if option.get('type') != 'null'
        ]
        return named[0] if named else 'null'
    declared = spec.get('type')
    if declared == 'array':
        return f'[{_render_type(spec.get("items", {}))}]'
    return str(declared or 'string')
