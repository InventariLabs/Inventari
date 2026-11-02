"""A router that catches a ``ValueError`` decides what the reader sees.

The global handler in ``app.main`` answers a ``ValueError`` by provenance: a
sentence this codebase wrote reaches the reader, a library's text (pydantic's
``ValidationError`` names the DTO, echoes ``input_value`` and links to
pydantic's docs) is answered with a translated generic sentence while the
traceback goes to the log. A router that catches the error itself and raises
``ValidationException(message=str(exc))`` decides nothing: creating a
category with an unknown field type answered a Polish reader with pydantic's
English, DTO name and all.

The rule: the text of a caught ``ValueError`` travels on only through
``refusal_text``, which applies the handler's provenance rule and raises a
library's error again so the handler can answer it.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap

import pytest
from pydantic import BaseModel, ValidationError

from app.core.exceptions import ServiceRejectionError, refusal_text

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'app'

#: Handlers that catch a library's ``ValueError`` by construction — a parse of
#: a spreadsheet, a URL, a UUID, an LLM's JSON — and hand its text on. The text
#: is the library's whatever the provenance rule says (the stdlib raises a
#: plain ``ValueError``), so ``refusal_text`` would pass it unchanged; each
#: needs a translated refusal of its own instead. Debt, not permission: an
#: entry that stops echoing fails ``test_no_exemption_outlives_its_echo``.
EXEMPT: dict[str, str] = {}


def _catches_value_error(node: ast.expr | None) -> bool:
    """Does an ``except`` clause with this type catch ``ValueError``?"""
    if isinstance(node, ast.Tuple):
        return any(_catches_value_error(element) for element in node.elts)
    if isinstance(node, ast.Name):
        return node.id == 'ValueError'
    if isinstance(node, ast.Attribute):
        return node.attr == 'ValueError'
    return False


def _echoes(expression: ast.expr, name: str) -> bool:
    """Does *expression* carry the caught exception's own text?

    ``str(exc)``, ``repr(exc)``, ``exc.args`` and ``f'{exc}'`` all put the
    sentence somebody else wrote into the answer.
    """
    for node in ast.walk(expression):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {'str', 'repr'}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == name
        ):
            return True
        if (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr == 'args'
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return True
    return False


def _qualname(tree: ast.AST, lineno: int) -> str:
    """The innermost function holding *lineno* — a key that survives edits."""
    best = '<module>'
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.lineno <= lineno <= (node.end_lineno or node.lineno):
            best = node.name
    return best


def echoes_in(source: str) -> list[tuple[int, str]]:
    """``(line, function)`` of every raise that echoes a caught ValueError."""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for handler in ast.walk(tree):
        if not (
            isinstance(handler, ast.ExceptHandler)
            and handler.name
            and _catches_value_error(handler.type)
        ):
            continue
        for statement in handler.body:
            for node in ast.walk(statement):
                if (
                    isinstance(node, ast.Raise)
                    and node.exc is not None
                    and _echoes(node.exc, handler.name)
                ):
                    found.append((node.lineno, _qualname(tree, node.lineno)))
    return found


def _tree_echoes() -> dict[str, list[int]]:
    """Every echo under ``app/``, keyed ``path::function``."""
    sites: dict[str, list[int]] = {}
    for path in sorted(APP_ROOT.rglob('*.py')):
        if 'tests' in path.parts or 'migrations' in path.parts:
            continue
        rel = path.relative_to(APP_ROOT.parent).as_posix()
        for line, function in echoes_in(path.read_text(encoding='utf-8')):
            sites.setdefault(f'{rel}::{function}', []).append(line)
    return sites


@pytest.mark.unit
class TestNoRouterDecidesProvenanceByNotDecidingIt:
    def test_no_caught_value_error_is_echoed(self) -> None:
        offenders = {
            key: lines for key, lines in _tree_echoes().items() if key not in EXEMPT
        }

        assert offenders == {}, (
            'These raises hand on the text of a caught ValueError, which may be '
            "a library's (pydantic names the DTO and echoes the input). Pass it "
            'through refusal_text(exc), or leave the error to the global handler: '
            f'{offenders}'
        )

    def test_no_exemption_outlives_its_echo(self) -> None:
        stale = sorted(set(EXEMPT) - set(_tree_echoes()))

        assert stale == [], f'Exempt, but no longer echoing — remove them: {stale}'


@pytest.mark.unit
class TestTheScanHasTeeth:
    @pytest.mark.parametrize(
        'raise_line',
        [
            'raise ValidationException(message=str(exc)) from exc',
            "raise ConflictException(code='X', message=str(exc)) from exc",
            "raise HTTPException(status_code=400, detail=f'Bad: {exc}')",
            'raise ValueError(str(exc)) from exc',
            'raise Refused(repr(exc))',
            'raise Refused(exc.args[0])',
        ],
    )
    def test_an_echo_is_found(self, raise_line: str) -> None:
        source = textwrap.dedent(
            f"""
            def endpoint():
                try:
                    work()
                except ValueError as exc:
                    {raise_line}
            """
        )

        assert echoes_in(source) == [(6, 'endpoint')]

    def test_a_tuple_with_value_error_counts(self) -> None:
        source = textwrap.dedent(
            """
            def endpoint():
                try:
                    work()
                except (KeyError, ValueError) as exc:
                    raise Refused(str(exc))
            """
        )

        assert echoes_in(source) == [(6, 'endpoint')]

    @pytest.mark.parametrize(
        'handler',
        [
            'except ValueError as exc:\n        raise Refused(refusal_text(exc))',
            'except ValueError as exc:\n        raise NotFoundException("x") from exc',
            'except KeyError as exc:\n        raise Refused(str(exc))',
            'except ValueError as exc:\n        logger.warning(str(exc))\n        raise',
        ],
        ids=['through refusal_text', 'no text', 'not a ValueError', 'logged only'],
    )
    def test_what_is_not_an_echo(self, handler: str) -> None:
        source = f'def endpoint():\n    try:\n        work()\n    {handler}\n'

        assert echoes_in(source) == []


class _Shape(BaseModel):
    kind: int


@pytest.mark.unit
class TestRefusalText:
    def test_a_sentence_we_wrote_is_handed_on(self) -> None:
        assert refusal_text(ValueError('Name is taken')) == 'Name is taken'

    def test_a_keyed_refusal_is_handed_on_translated(self) -> None:
        exc = ServiceRejectionError('invalid_input')

        assert refusal_text(exc) == str(exc)

    def test_a_librarys_error_goes_back_to_the_handler(self) -> None:
        with pytest.raises(ValidationError) as caught:
            _Shape(kind='not a number')  # type: ignore[arg-type]

        with pytest.raises(ValidationError) as again:
            refusal_text(caught.value)
        assert again.value is caught.value
