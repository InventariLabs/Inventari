"""Gate: a refusal never answers ``detail`` as a raw sentence literal.

``AppException`` and the handlers in ``app.main`` answer
``{"detail": {"code", "message", ...}}``; a client branches on ``code``
without reading prose. A raw ``raise HTTPException(detail='<English
sentence>')`` answers a string instead, and the same refusal then arrives in
a different shape depending on which route happened to raise it.

The literal scan is the rule, not a list: it walks every non-test module
under ``app/`` and fails on any ``HTTPException`` raise whose ``detail`` is a
string literal, an f-string or a catalogue lookup
(``get_error_message(...)``), wherever it is added. A translated sentence is
still a bare string: the reader sees the right language, and a client
branching on why it was refused gets nothing to branch on. Both populations
were migrated rather than grandfathered, so the count is zero; a refusal
answered at a status of its own goes through ``catalogue_status_refusal``,
which keeps the key as the ``code``.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / 'app'


def _http_exception_name(node: ast.expr) -> str | None:
    """The called name when *node* is ``HTTPException(...)``, bare or dotted."""
    if not isinstance(node, ast.Call):
        return None
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _detail_expression(call: ast.Call) -> ast.expr | None:
    """The value ``HTTPException`` will put under ``detail``.

    ``HTTPException(status_code, detail, headers)`` also accepts detail as
    the second positional argument, so both spellings are read.
    """
    for keyword in call.keywords:
        if keyword.arg == 'detail':
            return keyword.value
    if len(call.args) >= 2:
        return call.args[1]
    return None


def _is_catalogue_lookup(node: ast.expr | None) -> bool:
    """Is *node* ``get_error_message(...)``, bare or dotted?"""
    if not isinstance(node, ast.Call):
        return False
    target = node.func
    name = target.id if isinstance(target, ast.Name) else getattr(target, 'attr', None)
    return name == 'get_error_message'


def string_detail_raises(root: Path) -> list[tuple[str, int, str]]:
    """Discover ``HTTPException(detail=<sentence string>)`` sites.

    Every construction counts, not only a ``raise``: a helper that builds the
    exception and returns it for its caller to raise answers just the same.

    Returns ``(relative_path, lineno, sentence)``. A dict-shaped detail — the
    coded envelope — passes; a literal, an f-string and a catalogue lookup
    are each a sentence with no code next to it.
    """
    findings: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob('*.py')):
        relative = path.relative_to(root)
        if {'tests', '__pycache__', 'migrations'} & set(relative.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _http_exception_name(node) != 'HTTPException':
                continue
            detail = _detail_expression(node)
            if isinstance(detail, ast.Constant) and isinstance(detail.value, str):
                findings.append((relative.as_posix(), node.lineno, detail.value))
            elif isinstance(detail, ast.JoinedStr) or _is_catalogue_lookup(detail):
                findings.append((relative.as_posix(), node.lineno, ast.unparse(detail)))
    return findings


class TestTheRefusalEnvelopeCarriesACode:
    def test_no_http_refusal_answers_with_a_sentence(self) -> None:
        """A new raw sentence lights up without touching any list.

        A refusal that a person reads raises ``ConflictException``,
        ``ValidationException``, ``NotFoundException`` — or a handler builds
        the same object — so the answer always carries a ``code`` next to
        the sentence.
        """
        findings = string_detail_raises(APP_ROOT)

        assert findings == [], (
            'raise HTTPException(detail="<sentence>") answers a bare string — '
            'route it through the typed AppException classes so the client gets '
            f'a code: {findings[:10]}'
        )


class TestTheScanHasTeeth:
    def _scan(self, tmp_path: Path, body: str) -> list[tuple[str, int, str]]:
        target = tmp_path / 'app' / 'modules'
        target.mkdir(parents=True)
        (target / 'thing.py').write_text(body, encoding='utf-8')
        return string_detail_raises(tmp_path / 'app')

    def test_a_literal_sentence_is_found(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refuse():\n'
            "    raise HTTPException(status_code=409, detail='Period is closed.')\n",
        )

        assert found == [('modules/thing.py', 3, 'Period is closed.')]

    def test_an_fstring_sentence_is_found(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refuse(name):\n'
            '    raise HTTPException(\n'
            '        status_code=409, detail=f"A list named {name} already exists."\n'
            '    )\n',
        )

        assert [entry[2] for entry in found] == [
            "f'A list named {name} already exists.'"
        ]

    def test_a_positional_detail_is_found(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refuse():\n'
            "    raise HTTPException(409, 'Period is closed.')\n",
        )

        assert found == [('modules/thing.py', 3, 'Period is closed.')]

    def test_a_catalogue_sentence_is_found(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refuse(lang):\n'
            '    raise HTTPException(\n'
            "        status_code=404, detail=get_error_message('recipe_not_found', lang)\n"
            '    )\n',
        )

        assert [entry[2] for entry in found] == [
            "get_error_message('recipe_not_found', lang)"
        ]

    def test_a_returned_exception_is_found(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refusal(lang):\n'
            '    return HTTPException(\n'
            "        status_code=503, detail=get_error_message('ai_off', lang)\n"
            '    )\n',
        )

        assert [entry[1] for entry in found] == [3]

    def test_a_coded_detail_passes(self, tmp_path: Path) -> None:
        found = self._scan(
            tmp_path,
            'from fastapi import HTTPException\n'
            'def refuse():\n'
            '    raise HTTPException(\n'
            "        status_code=409, detail={'code': 'PERIOD_CLOSED', 'message': 'Closed'}\n"
            '    )\n',
        )

        assert found == []
