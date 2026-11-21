"""A body that breaks a schema is answered in the application's words.

Passes this comes from: the 2026-11 QA round met "Decimal input should have no
more than 8 digits before the decimal point" in a toast (stock take screen),
"1 validation error for create_itemArguments" from the MCP ``create_item``
tool, and a bare English sentence as the 413 body-size refusal. Each was fixed
where it was found; this file keeps the class at zero.

The rule. Every write route of the assembled application (core and every
module) has a body schema. For each one this builds bodies that break it —
a missing field, a value of the wrong type, a value outside a declared bound,
one that does not match a declared format — and runs pydantic's own errors
through the same ``translate_validation_error`` the 422 handler uses. An
error whose answer is still the library's sentence, word for word, is a
refusal in the library's words. A validator's own ``ValueError`` (a sentence
this codebase wrote) and a keyed refusal are application text and pass.

``library_validation_sentences_baseline.txt`` names the error *types* still
answered in the library's words — today the "wrong JSON type" family
(``string_type``, ``model_type``, …), which a client of this API can send but
the screens cannot, because a form hands over the type the field declares.
The goal is an empty file. A constraint that reaches the reader through an
error type the catalogue does not carry (a list's minimum length, a decimal's
digits, a new format) is a type that is not in the baseline, and fails here
instead of in a toast.

The MCP tools take the same rule through their own transport: a tool called
with arguments that break its schema answers with a named refusal, never with
the server library's validation text.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.i18n._validation import translate_validation_error
from app.main import app

BASELINE = (
    Path(__file__).parent.parent
    / 'fixtures'
    / 'library_validation_sentences_baseline.txt'
)

_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_MAX_DEPTH = 3


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while '$ref' in node:
        node = defs[node['$ref'].rsplit('/', 1)[-1]]
    return node


def _bad_strings(node: dict[str, Any]) -> Iterator[Any]:
    yield 12345
    yield []
    if 'maxLength' in node:
        yield 'x' * (node['maxLength'] + 1)
    if node.get('minLength'):
        yield ''
    if 'pattern' in node:
        yield '\u2603\u2603'
    if node.get('format') in {'uuid', 'date', 'date-time', 'email'}:
        yield 'not-a-value'


def _bad_numbers(node: dict[str, Any]) -> Iterator[Any]:
    yield 'abc'
    yield {}
    for bound, step in (
        ('minimum', -1),
        ('exclusiveMinimum', -1),
        ('maximum', 1),
        ('exclusiveMaximum', 1),
    ):
        if bound in node:
            yield node[bound] + step


def _bad_arrays(
    node: dict[str, Any], defs: dict[str, Any], depth: int
) -> Iterator[Any]:
    yield 'x'
    if node.get('minItems'):
        yield []
    if 'maxItems' in node:
        yield [None] * (node['maxItems'] + 1)
    if depth < _MAX_DEPTH and 'items' in node:
        for bad in _bad_values(node['items'], defs, depth + 1):
            yield [bad]


def _bad_objects(
    node: dict[str, Any], defs: dict[str, Any], depth: int
) -> Iterator[Any]:
    yield 'x'
    if depth < _MAX_DEPTH:
        yield {}
        for name, prop in node.get('properties', {}).items():
            for bad in _bad_values(prop, defs, depth + 1):
                yield {name: bad}


def _bad_values(
    node: dict[str, Any], defs: dict[str, Any], depth: int
) -> Iterator[Any]:
    """Values that break ``node``: wrong type, past a bound, off a format."""
    node = _resolve(node, defs)
    for branch in node.get('anyOf', []) + node.get('oneOf', []):
        if branch.get('type') != 'null':
            yield from _bad_values(branch, defs, depth)
    for branch in node.get('allOf', []):
        yield from _bad_values(branch, defs, depth)
    if 'enum' in node or 'const' in node:
        yield '__not_a_choice__'
    kind = node.get('type')
    if kind == 'string':
        yield from _bad_strings(node)
    elif kind in {'integer', 'number'}:
        yield from _bad_numbers(node)
    elif kind == 'boolean':
        yield 'maybe'
    elif kind == 'array':
        yield from _bad_arrays(node, defs, depth)
    elif kind == 'object' or 'properties' in node:
        yield from _bad_objects(node, defs, depth)


def _decimal_probes() -> list[Any]:
    """The probes JSON schema cannot describe: a Decimal's digits."""
    return ['1' * 40, '0.' + '1' * 20]


def _bodies(annotation: Any) -> Iterator[Any]:
    adapter = TypeAdapter(annotation)
    schema = adapter.json_schema(mode='validation')
    defs = schema.get('$defs', {})
    yield {}
    yield from _bad_values(schema, defs, 0)
    node = _resolve(schema, defs)
    for name in node.get('properties', {}):
        for probe in _decimal_probes():
            yield {name: probe}


def write_body_schemas() -> dict[str, Any]:
    """Every write route's body annotation, keyed by ``<module>.<name>``."""
    found: dict[str, Any] = {}
    for node in app.routes:
        contexts = (
            node.effective_route_contexts()
            if hasattr(node, 'effective_route_contexts')
            else []
        )
        for ctx in contexts:
            if not (ctx.methods and ctx.methods & _WRITE_METHODS and ctx.dependant):
                continue
            for param in ctx.dependant.body_params:
                annotation = param.field_info.annotation
                label = (
                    getattr(annotation, '__module__', '?')
                    + '.'
                    + getattr(annotation, '__qualname__', str(annotation))
                )
                found[label] = annotation
    return found


def _errors_of(adapter: TypeAdapter, body: Any) -> list[Any]:
    """The pydantic errors a body raises; none when it validates.

    A before-validator that crashes on a wrong type raises something else — a
    500, a different defect, not a sentence — and yields no errors here.
    """
    try:
        adapter.validate_python(body)
    except ValidationError as exc:
        return list(exc.errors())
    except (AttributeError, TypeError, KeyError, ArithmeticError):
        return []
    return []


def library_worded(annotation: Any) -> dict[str, str]:
    """Error types of ``annotation`` still answered in the library's words."""
    adapter = TypeAdapter(annotation)
    found: dict[str, str] = {}
    for body in _bodies(annotation):
        for error in _errors_of(adapter, body):
            ours = (error.get('ctx') or {}).get('error') is not None
            if ours or error['type'] in {'value_error', 'assertion_error'}:
                continue
            if translate_validation_error(dict(error), 'en') == error['msg']:
                found.setdefault(error['type'], error['msg'])
    return found


def _baseline() -> set[str]:
    lines = BASELINE.read_text(encoding='utf-8').splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith('#')}


def current_findings() -> dict[str, str]:
    """Library-worded error type → one schema that produces it."""
    found: dict[str, str] = {}
    for label, annotation in write_body_schemas().items():
        for kind in library_worded(annotation):
            found.setdefault(kind, label)
    return found


def test_a_write_body_is_not_refused_in_the_librarys_words() -> None:
    found = current_findings()
    new = {kind: label for kind, label in found.items() if kind not in _baseline()}

    assert not new, (
        "a write body that breaks its schema is answered in pydantic's own "
        'English. Add the error type to _VALIDATION_TEMPLATES in '
        'app/i18n/_validation.py (and its catalogue key in every language), '
        'or give the field a validator that refuses with a keyed message:\n  '
        + '\n  '.join(f'{kind}  (e.g. {label})' for kind, label in sorted(new.items()))
    )


def test_the_baseline_names_only_types_that_still_reach_a_reader() -> None:
    stale = sorted(_baseline() - set(current_findings()))

    assert not stale, 'translated now — remove from the baseline:\n  ' + '\n  '.join(
        stale
    )


def test_a_planted_library_sentence_is_found() -> None:
    """The scan has teeth: a field only pydantic words is reported."""

    class Planted(BaseModel):
        tags: Annotated[list[str], Field(min_length=1)]
        blob: bytes

    planted = library_worded(Planted)
    assert 'bytes_type' in planted
    assert 'bytes_type' not in _baseline()


def test_a_translated_constraint_is_not_a_library_sentence() -> None:
    class Translated(BaseModel):
        name: Annotated[str, Field(max_length=5)]
        amount: Annotated[Decimal, Field(max_digits=4)]

    assert not set(library_worded(Translated)) - {
        'string_type',
        'decimal_type',
        'model_type',
    }
