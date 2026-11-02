"""The refusal list tracks the formats the interpreter can execute.

``UNREADABLE_EXECUTABLE_SUFFIXES`` is hand-written, and it is a security
property: every suffix the import system loads as code that is not ``.py``
source is a format the safety scan cannot read. A new Python version or ABI
adds an entry to ``importlib.machinery.all_suffixes()``; if the literal does
not follow, the installer starts admitting a format the scan never saw while
every gate stays green.
"""

from __future__ import annotations

import importlib.machinery

from app.cli._module_signing import UNREADABLE_EXECUTABLE_SUFFIXES


def _ends_with_any(name: str, suffixes: frozenset[str]) -> bool:
    return any(name.endswith(s) for s in suffixes)


def test_every_non_source_import_suffix_is_refused() -> None:
    # Extension suffixes are compound ('.cpython-313-x86_64-linux-gnu.so'),
    # so coverage means the entry ends in a refused suffix, not equals one.
    uncovered = [
        s
        for s in importlib.machinery.all_suffixes()
        if s not in importlib.machinery.SOURCE_SUFFIXES
        and not _ends_with_any(s, UNREADABLE_EXECUTABLE_SUFFIXES)
    ]
    assert not uncovered, (
        f'import suffixes the scan cannot read and the installer would admit: '
        f'{uncovered} — add them to UNREADABLE_EXECUTABLE_SUFFIXES'
    )


def test_source_suffixes_are_never_refused() -> None:
    assert not [
        s
        for s in importlib.machinery.SOURCE_SUFFIXES
        if _ends_with_any(s, UNREADABLE_EXECUTABLE_SUFFIXES)
    ]
