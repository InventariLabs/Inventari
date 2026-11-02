"""Guardrail: escape-hatch marker must not appear in Core ``app/services/``.

The ``# architecture: allow_direct_db_access`` marker is reserved for MODULE
code (``app/modules/**``) that needs read-only Core table access it cannot
get through CoreAPI. Core services (``app/services/**``) write to Core-owned
models directly and legitimately — they are not escape hatches. Allowing the
marker there is misleading (it claims read-only analytics while the file may
perform writes) and blurs the Core/module boundary.

This check emits a ``::error`` per ``app/services/**/*.py`` (excluding tests)
that contains the marker as a standalone directive (i.e. at the start of a
line, after optional leading whitespace), so such cases are caught at lint
time rather than surviving as misleading documentation. Occurrences inside
prose/docstrings are not flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._constants import _is_test_file, _rel_parts

# The escape-hatch marker that is reserved for module code.
ESCAPE_HATCH_MARKER = '# architecture: allow_direct_db_access'

# Matches the marker only when it starts a line (after optional leading whitespace),
# so it is treated as a real directive rather than prose inside a docstring/comment.
_MARKER_LINE_RE = re.compile(r'^[ \t]*' + re.escape(ESCAPE_HATCH_MARKER), re.M)


def _check_services_escape_hatch_marker(services_root: Path) -> list[str]:
    """Emit ``::error`` per ``app/services/**/*.py`` containing the escape-hatch marker.

    Only standalone marker directives (start of line, after optional whitespace)
    are flagged; occurrences inside prose/docstrings are ignored.

    Args:
        services_root: the ``app/services/`` directory to scan.

    Returns:
        list[str]: one GitHub-PR-formatted annotation per offending file.
    """
    if not services_root.is_dir():
        return []
    errors: list[str] = []
    for py_file in services_root.rglob('*.py'):
        if _is_test_file(py_file, services_root) or '__pycache__' in _rel_parts(
            py_file, services_root
        ):
            continue
        try:
            source = py_file.read_text(encoding='utf-8')
        except (SyntaxError, UnicodeDecodeError):
            continue
        match = _MARKER_LINE_RE.search(source)
        if match is None:
            continue
        # Report the line number of the marker for a clickable annotation.
        line_no = source.count('\n', 0, match.start()) + 1
        try:
            rel = py_file.relative_to(Path.cwd())
        except ValueError:
            rel = py_file
        errors.append(
            f'::error file={rel},line={line_no},'
            f'title=Architecture: escape-hatch marker in Core services::'
            f"the '{ESCAPE_HATCH_MARKER}' marker is reserved for module code "
            f'(app/modules/**). Core services write to Core-owned models '
            f'directly and legitimately; the marker is misleading here. '
            f'Remove it (AGENTS.md §3 Escape Hatch).'
        )
    return errors
