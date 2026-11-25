"""A tool called with arguments that break its schema answers in words of ours.

Passes this comes from: the 2026-11 QA round called ``create_item`` without a
location and read "1 validation error for create_itemArguments ... For further
information visit https://errors.pydantic.dev" — the server library's own
validation text, which tells an agent neither what is missing nor what to call
next. The omitted-location case is fixed where it was found
(``test_write_tools.py``); this walks every tool of the catalogue so the next
one added cannot answer the same way.

Each tool is called with no arguments and then with each declared argument
given a value of the wrong type. An answer is a refusal (``isError``) whose
text carries none of the fragments the libraries put in theirs; the baseline
below names the (tool, argument) pairs that still do, and the goal is an
empty one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SNAPSHOT = Path(__file__).parent.parent / 'snapshots' / 'tools.json'

#: Fragments the MCP server library and pydantic put in their validation text.
LIBRARY_FRAGMENTS = (
    'validation error for',
    'errors.pydantic.dev',
    'Input should be',
    'Field required',
    'Error executing tool',
)

#: (tool, case) pairs still answered in the library's text. Empty: argument
#: validation is answered by the server itself (``_http._InventariServer``).
#: A pair added here is debt, never permission.
BASELINE: frozenset[str] = frozenset()


def _tools() -> list[dict[str, Any]]:
    data = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    return data if isinstance(data, list) else data.get('tools', data)


def _cases() -> list[tuple[str, str, dict[str, Any]]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []
    for tool in _tools():
        name = tool['name']
        cases.append((name, 'no arguments', {}))
        for prop in tool.get('inputSchema', {}).get('properties', {}):
            cases.append((name, f'{prop} of the wrong type', {prop: {'wrong': 1}}))
    return cases


def library_worded(text: str) -> list[str]:
    return [fragment for fragment in LIBRARY_FRAGMENTS if fragment in text]


@pytest.mark.parametrize(
    ('tool', 'case', 'arguments'),
    _cases(),
    ids=[f'{tool}:{case}' for tool, case, _ in _cases()],
)
def test_a_tool_refusal_is_not_the_librarys_text(
    mcp_tool, mcp_write_key: str, tool: str, case: str, arguments: dict[str, Any]
) -> None:
    result = mcp_tool(mcp_write_key, tool, arguments)

    text = ' '.join(part.get('text', '') for part in result.get('content', []))
    if f'{tool}:{case}' in BASELINE:
        assert library_worded(text), (
            f"{tool} ({case}) no longer answers in the library's words — "
            'remove it from BASELINE.'
        )
        return
    assert not library_worded(text), (
        f"{tool} ({case}) answers in the library's words: {text[:200]!r}. "
        'Refuse with a named code and a sentence that says what to send.'
    )


def test_the_scan_sees_the_librarys_text() -> None:
    """A planted answer in the library's voice is recognised."""
    planted = (
        '1 validation error for create_itemArguments\nlocation_id\n'
        '  Field required [type=missing]\n'
        '    For further information visit https://errors.pydantic.dev/2.12/'
    )
    assert library_worded(planted)
    assert not library_worded('LOCATION_REQUIRED: choose a location first')


def test_an_omitted_argument_is_named_with_what_to_send(
    mcp_tool, mcp_write_key: str
) -> None:
    """The refusal names the argument and says what it is, from the tool's
    own published description, so an agent knows which call gives it one."""
    result = mcp_tool(mcp_write_key, 'get_item', {})

    assert result['isError'] is True
    text = result['content'][0]['text']
    assert text.startswith('ARGUMENT_REQUIRED: ')
    assert 'item_id' in text
    assert 'search_items' in text


def test_an_argument_of_the_wrong_type_says_which_type(
    mcp_tool, mcp_write_key: str
) -> None:
    result = mcp_tool(mcp_write_key, 'get_item', {'item_id': 'not-an-id'})

    assert result['isError'] is True
    text = result['content'][0]['text']
    assert text.startswith('ARGUMENT_INVALID: ')
    assert 'item_id' in text
    assert 'uuid' in text
    assert 'not-an-id' not in text


def test_a_refusal_of_the_tool_itself_carries_no_library_prefix(
    mcp_tool, mcp_write_key: str
) -> None:
    """A tool's own refusal reaches the agent as written: code first."""
    result = mcp_tool(
        mcp_write_key,
        'get_item',
        {'item_id': '00000000-0000-0000-0000-000000000000'},
    )

    assert result['isError'] is True
    assert result['content'][0]['text'].startswith('ITEM_NOT_FOUND: ')
