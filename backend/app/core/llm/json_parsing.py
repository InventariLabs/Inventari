"""Resilient JSON extraction for LLM responses.

Models are asked for JSON and answer with something JSON-adjacent: wrapped in
a markdown fence, prefixed with "Here is the JSON:", carrying a literal
newline inside a string value, or cut in half by the token budget. Every call
site used to cope with that on its own and at a different level of paranoia,
so the same model output parsed fine in recipes and raised a 500 in vision.

This module is the one shared answer. It is Core and stdlib-only by design —
it has to be importable from any module and from Core itself.

The pipeline, ordered by how much it assumes:

1. parse the text as it came,
2. escape control characters the model left raw inside string literals,
3. cut out each balanced ``{...}`` / ``[...]`` block and retry per block,
4. for a block the response ended in the middle of, close what is still open.

Domain concerns stay with the caller: unwrapping vision's ``{"product": …}``
envelope, coercing decimals, validating UUIDs. This module returns whatever
the model actually sent, or raises ``json.JSONDecodeError``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

__all__ = [
    'extract_json',
    'extract_json_object',
    'repair_json_strings',
    'strip_markdown_fence',
]

_FENCED_BLOCK = re.compile(r'```[ \t]*(?:json)?[ \t]*\r?\n?(.*?)```', re.DOTALL | re.I)
_LEADING_FENCE = re.compile(r'^\s*```[ \t]*(?:json)?[ \t]*\r?\n?', re.I)
_TRAILING_FENCE = re.compile(r'\s*```\s*$')

_OPENERS = {'{': '}', '[': ']'}
_CLOSERS = frozenset(_OPENERS.values())


def strip_markdown_fence(text: str) -> str:
    """Return the payload of the first markdown code fence, or ``text`` itself.

    Handles a fence sitting in the middle of prose ("Here is the JSON:
    ```…```, hope that helps"). An unterminated fence — the shape a truncated
    response takes — loses only its opener.
    """
    match = _FENCED_BLOCK.search(text)
    if match:
        return match.group(1).strip()
    return _TRAILING_FENCE.sub('', _LEADING_FENCE.sub('', text).strip())


def repair_json_strings(s: str) -> str:
    """Escape control characters a model left raw inside string literals.

    ``{"title": "line1<LF>line2"}`` is not valid JSON, but it is what models
    produce for multi-line instructions. Characters outside string literals
    are untouched, so ordinary pretty-printed JSON passes through unchanged.
    """
    result: list[str] = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


def extract_json(text: str) -> Any:
    """Pull the JSON value out of a model response.

    Returns whatever the model sent — an object, a list, or a scalar. Raises
    ``json.JSONDecodeError`` when nothing in the text parses, which is the
    signal that the model answered in prose rather than in the agreed format.
    """
    unfenced = strip_markdown_fence(text)
    tried: set[str] = set()
    for fragment in _fragments(unfenced, text):
        for candidate in _repairs(fragment):
            if candidate in tried:
                continue
            tried.add(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError('No JSON value found in the model response', text, 0)


def extract_json_object(text: str) -> dict[str, Any]:
    """:func:`extract_json` with a guarantee that the payload is an object.

    Raises ``TypeError`` when the model returned a list or a scalar. That is a
    different failure from "no JSON at all" and call sites usually want to
    treat it differently — often by unwrapping the list themselves.
    """
    value = extract_json(text)
    if not isinstance(value, dict):
        raise TypeError(f'Expected a JSON object, got {type(value).__name__}')
    return value


# --- internals ---------------------------------------------------------------


@dataclass(frozen=True)
class _Structure:
    """What one string-aware walk over a fragment found."""

    open_stack: str
    """Brackets still open at the end of the fragment, outermost first."""

    ends_in_string: bool
    """The fragment stops inside an unterminated string literal."""

    first_block_end: int | None
    """Index just past the first balanced block, or ``None`` if it never closed."""

    last_comma: int
    """Index of the last comma outside a string literal, or ``-1``."""


def _scan(text: str, start: int = 0) -> _Structure:
    """Walk ``text`` from ``start``, tracking string literals and escapes.

    One loop answers every structural question the parser asks, so the rule
    that actually matters — a brace inside a string is not a brace — lives in
    exactly one place.
    """
    stack: list[str] = []
    in_string = False
    escape_next = False
    first_block_end: int | None = None
    last_comma = -1

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
        elif ch == '\\' and in_string:
            escape_next = True
        elif ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch in _OPENERS:
            stack.append(ch)
        elif ch in _CLOSERS:
            if stack and _OPENERS[stack[-1]] == ch:
                stack.pop()
                if not stack and first_block_end is None:
                    first_block_end = i + 1
        elif ch == ',':
            last_comma = i

    return _Structure(''.join(stack), in_string, first_block_end, last_comma)


def _json_blocks(text: str) -> Iterator[str]:
    """Yield each top-level ``{...}`` / ``[...]`` block, in order of appearance.

    Yielding more than the first block matters when the model prefixes its
    answer with a pseudo-JSON aside — the real payload is the second block.
    A block the text ends in the middle of is yielded unclosed; completing it
    is :func:`_repairs`' job.
    """
    pos = 0
    while pos < len(text):
        starts = [i for i in (text.find('{', pos), text.find('[', pos)) if i != -1]
        if not starts:
            return
        start = min(starts)
        end = _scan(text, start).first_block_end
        if end is None:
            yield text[start:]
            return
        yield text[start:end]
        pos = end


def _fragments(unfenced: str, original: str) -> Iterator[str]:
    """The substrings worth trying, widest first."""
    yield unfenced
    yield from _json_blocks(unfenced)
    if original != unfenced:
        yield original
        yield from _json_blocks(original)


def _repairs(fragment: str) -> Iterator[str]:
    """The fragment itself, then progressively more assertive repairs."""
    yield fragment

    repaired = repair_json_strings(fragment)
    if repaired != fragment:
        yield repaired

    # A response the token budget cut short. Close what is still open, in
    # order of how much data the repair throws away: keep everything, then
    # drop the member that got truncated, then salvage a half-written string.
    body = repaired.rstrip()
    structure = _scan(body)

    as_is = _complete(body, structure)
    if as_is is not None:
        yield as_is

    if structure.last_comma != -1:
        head = body[: structure.last_comma]
        without_partial = _complete(head, _scan(head))
        if without_partial is not None:
            yield without_partial

    if structure.ends_in_string:
        quoted = body + '"'
        salvaged = _complete(quoted, _scan(quoted))
        if salvaged is not None:
            yield salvaged


def _complete(prefix: str, structure: _Structure) -> str | None:
    """Close the brackets a truncated fragment still has open.

    ``None`` means there is nothing to complete: either the fragment is
    already balanced, or it ends inside a string literal — a case the caller
    offers separately, with the closing quote already added.
    """
    if structure.ends_in_string or not structure.open_stack:
        return None
    return prefix + ''.join(_OPENERS[b] for b in reversed(structure.open_stack))
