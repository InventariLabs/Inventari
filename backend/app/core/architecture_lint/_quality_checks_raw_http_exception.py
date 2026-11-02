"""Guardrail: a new raw ``HTTPException`` raise is a decision, not a habit.

AGENTS.md §3 sends routers through the typed ``AppException`` subclasses —
``NotFoundException``, ``ForbiddenException``, ``ConflictException``,
``ValidationException`` — which answer ``detail = {code, message}``. A raw
``raise HTTPException(...)`` answers ``detail`` as a plain string: the
client gets a sentence and no code to branch on.

The tree holds no raw raises any more, and the baseline is empty. A site
would be keyed ``path::qualname@N`` (the Nth raw raise inside that function),
and a new one has to be a conscious act: answer through a typed exception, or
move the baseline and the size ratchet in the same reviewable diff.

The scan is AST-based, so a ``raise HTTPException`` named in a docstring or
a comment is prose, not a finding.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ._constants import _is_test_file, _rel_parts
from ._quality_checks_transaction_ownership import _enclosing_qualname
from ._run_cache import once_per_run


@dataclass(frozen=True)
class RawHttpExceptionSite:
    """One raw ``raise HTTPException(...)``, keyed per site.

    ``ordinal`` is the 1-based position of this raise among the raises in
    the same function, so a second raw raise added to a baselined function
    is a new, uncovered site rather than a free rider on the old key.
    """

    rel_path: str
    qualname: str
    ordinal: int
    lineno: int

    @property
    def key(self) -> str:
        return f'{self.rel_path}::{self.qualname}@{self.ordinal}'


def _is_http_exception_call(node: ast.expr | None) -> bool:
    """Is this expression ``HTTPException(...)``, bare or attribute-qualified?"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == 'HTTPException'
    if isinstance(func, ast.Attribute):
        return func.attr == 'HTTPException'
    return False


@once_per_run
def _collect_raw_http_exceptions(roots: list[Path]) -> list[RawHttpExceptionSite]:
    """Every raw ``raise HTTPException(...)`` under *roots*, tests excluded."""
    sites: list[RawHttpExceptionSite] = []
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob('*.py')):
            rel = _rel_parts(py_file, root)
            if _is_test_file(py_file, root) or '__pycache__' in rel:
                continue
            if 'architecture_lint' in rel:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8'))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            raises: list[tuple[int, int]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and _is_http_exception_call(node.exc):
                    raises.append((node.lineno, node.col_offset))
            raises.sort()
            ordinals: dict[str, int] = {}
            for line_no, _col in raises:
                qualname = _enclosing_qualname(tree, line_no)
                ordinals[qualname] = ordinals.get(qualname, 0) + 1
                sites.append(
                    RawHttpExceptionSite(
                        rel_path='/'.join(rel),
                        qualname=qualname,
                        ordinal=ordinals[qualname],
                        lineno=line_no,
                    )
                )
    return sites


def _check_raw_http_exceptions(
    roots: list[Path], baseline: set[str] | None = None
) -> list[str]:
    """Emit ``::error``/``::notice`` per raw ``raise HTTPException``.

    Args:
        roots: the directories to scan (``app/``).
        baseline: ``relative/path.py::qualname@N`` sites accepted for now.

    Returns:
        list[str]: GitHub-PR-formatted annotations.
    """
    accepted = baseline or set()
    entries: list[str] = []
    for site in _collect_raw_http_exceptions(roots):
        is_baselined = site.key in accepted
        entries.append(
            f'::{"notice" if is_baselined else "error"} '
            f'{site.rel_path}:{site.lineno}: raise HTTPException inside '
            f'{site.qualname} — AGENTS.md §3: answer through the typed '
            f'AppException subclasses (NotFoundException, ForbiddenException, '
            f'ConflictException, ValidationException) or @map_service_errors; '
            f'a raw HTTPException answers detail as a bare string, so the '
            f'client gets no code.'
        )
    return entries
