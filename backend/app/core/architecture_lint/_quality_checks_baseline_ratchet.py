"""A baseline may shrink on its own; growing it takes a deliberate act.

Eight architecture gates split their findings into blocking ``::error`` and
grandfathered ``::notice`` purely on whether a key appears in a ``.txt``
file next to the code. The comment at the top of each of those files says
the list only ever gets shorter. Nothing enforced it: appending one line
silenced a finding, in the same commit as the code that caused it, and the
build stayed green.

So the sizes live in one committed file. An ordinary run compares them and
refuses any mismatch; ``--write-baseline-sizes`` is the only way to change
it. That does not make a suppression impossible -- nothing can -- but it
moves it out of the file the reviewer skims and into a one-line diff whose
whole content is "this gate now covers less than it did".

Shrinking fails too, with a different message. A ratchet that lets the
number drift down without being written back is a ratchet with slack: the
next addition would spend the room a paid debt left behind, and no diff
would show it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

#: Suppression lists live beside the code they cover, in ``app/core/``.
_BASELINE_GLOBS = ('*_baseline.txt', '*_deferrals.txt')


def _entry_count(path: Path) -> int:
    """Entries in a suppression list: non-empty, non-comment lines."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))


_WHITELIST_BEGIN_RESERVED = '# --- begin reserved surface'
_WHITELIST_END_RESERVED = '# --- end reserved surface'
WHITELIST_KEY = 'vulture_whitelist.py'


def _whitelist_count(path: Path) -> int:
    """Names the whitelist marks as used outside the reserved section.

    The reserved section is held to owner/expiry by its own rule; every
    other entry is a claim "a caller exists, the scanner cannot see it" that
    nothing but this count would notice growing. What counts as a use is
    vulture's own notion, not a list of statement shapes kept here (four
    rounds of shapes — comment spellings, ``assert``, ``del``, ``__all__``
    strings, aliased imports, longer attribute chains — each left one the
    counter did not know). So the file, with the reserved lines blanked, is
    handed to vulture's scanner and the number of distinct names it recorded
    as used is the count.
    """
    # vulture ships no type information; loading it by name keeps mypy quiet
    # without a suppression.
    vulture_class = importlib.import_module('vulture.core').Vulture

    try:
        source = path.read_text(encoding='utf-8')
        ast.parse(source)
    except (OSError, SyntaxError):
        return 0
    kept: list[str] = []
    inside = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(_WHITELIST_BEGIN_RESERVED):
            inside = True
        blank = inside
        if inside and stripped.startswith(_WHITELIST_END_RESERVED):
            inside = False
        kept.append('' if blank else line)
    scanner = vulture_class()
    scanner.scan('\n'.join(kept) + '\n')
    return len(scanner.used_names)


def iter_baseline_files(core_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in _BASELINE_GLOBS:
        files.extend(core_dir.glob(pattern))
    return sorted(files)


def current_sizes(core_dir: Path, whitelist_file: Path | None = None) -> dict[str, int]:
    sizes = {path.name: _entry_count(path) for path in iter_baseline_files(core_dir)}
    if whitelist_file is not None:
        sizes[WHITELIST_KEY] = _whitelist_count(whitelist_file)
    return sizes


def read_recorded_sizes(sizes_file: Path) -> dict[str, int]:
    if not sizes_file.exists():
        return {}
    recorded: dict[str, int] = {}
    for raw in sizes_file.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, _, count = line.partition(' ')
        try:
            recorded[name] = int(count.strip())
        except ValueError:
            continue
    return recorded


def write_baseline_sizes(
    core_dir: Path, sizes_file: Path, whitelist_file: Path | None = None
) -> int:
    """Record the current sizes. Returns how many lists were written."""
    sizes = current_sizes(core_dir, whitelist_file)
    body = '\n'.join(f'{name} {count}' for name, count in sorted(sizes.items()))
    sizes_file.write_text(
        '# Entry count per architecture suppression list — the ratchet.\n'
        '# Format: <file name> <entries>\n'
        '#\n'
        '# Written by `python -m app.core.architecture_lint '
        '--write-baseline-sizes`.\n'
        '# A plain run fails on any mismatch, so a line appended to a\n'
        '# baseline shows up here as a one-line diff saying the gate now\n'
        '# covers less than it did.\n'
        f'{body}\n',
        encoding='utf-8',
    )
    return len(sizes)


def _where(name: str) -> str:
    if name == WHITELIST_KEY:
        return f'backend/scripts/{name}'
    return f'app/core/{name}'


def _check_baseline_sizes(
    core_dir: Path, sizes_file: Path, whitelist_file: Path | None = None
) -> list[str]:
    """Emit ``::error`` for every suppression list that changed size."""
    rel = f'app/core/{sizes_file.name}'
    recorded = read_recorded_sizes(sizes_file)
    actual = current_sizes(core_dir, whitelist_file)
    errors: list[str] = []

    for name in sorted(set(recorded) | set(actual)):
        before = recorded.get(name)
        now = actual.get(name)
        if before == now:
            continue
        if before is None:
            errors.append(
                f'::error file={rel},title=Architecture: unrecorded baseline::'
                f'{name} is not in the ratchet. A new suppression list starts '
                f'at its current size: run `--write-baseline-sizes`.'
            )
        elif now is None:
            errors.append(
                f'::error file={rel},title=Architecture: baseline vanished::'
                f'{name} is recorded here but no longer exists. Drop the line '
                f'with `--write-baseline-sizes`.'
            )
        elif now > before:
            errors.append(
                f'::error file={_where(name)},title=Architecture: baseline grew::'
                f'{name} went from {before} to {now} entries. A gate now covers '
                f'less than it did — which, in the same change the gate was '
                f'meant to inspect, makes "gates green" mean nothing for the '
                f'rest of the diff. Fix the finding, or record the decision '
                f'with `--write-baseline-sizes` so the diff says so.'
            )
        else:
            errors.append(
                f'::error file={_where(name)},title=Architecture: ratchet has slack::'
                f'{name} went from {before} to {now} entries — debt was paid, '
                f'which is the good direction. Lower the ratchet with '
                f'`--write-baseline-sizes`, or the room it left is spent by '
                f'the next addition without a diff to show it.'
            )
    return errors


def _check_stale_entries(
    baseline: set[str], live: set[str], baseline_name: str
) -> list[str]:
    """Emit ``::error`` for every baseline entry that matches no finding.

    The size ratchet only sees how many entries a list has; it cannot tell a
    live entry from one whose code was deleted or moved. Such an entry reads
    as a recorded decision -- "we know about this risk" -- about a risk that
    is gone, and it keeps the list longer than the debt it stands for. It
    blocks (rather than informs) because the fix is mechanical: delete the
    line, then lower the ratchet with ``--write-baseline-sizes``.
    """
    return [
        f'::error file=app/core/{baseline_name},title=Architecture: stale baseline entry::'
        f'{entry!r} matches no finding any more. The code it described was '
        f'fixed, moved or deleted -- remove the line, then run '
        f'`--write-baseline-sizes`.'
        for entry in sorted(baseline - live)
    ]
