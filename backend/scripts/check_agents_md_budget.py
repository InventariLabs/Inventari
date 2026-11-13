#!/usr/bin/env python3
"""Gate: the agent instruction files do not grow past their recorded size.

``AGENTS.md``, ``backend/AGENTS.md``, ``frontend/AGENTS.md`` and ``CLAUDE.md``
are read at the start of every agent session, so every line added to one is
paid for by every session that follows. Each new lesson is worth a line to the
person writing it, and nobody sees the total grow: this gate does.

It is a ratchet, like the frontend coverage floors. ``agents-md-budget.json``
records the size in bytes of each file as measured on the commit that wrote the
number. A file larger than its entry fails ``make lint``; a smaller one passes,
and the entry can be lowered in any commit.

Raising an entry takes a commit of its own that changes nothing else, replaces
the measurement in the file, and says in its message what was added to which
file and why it has to be there — a size cannot be eased in the same commit as
the lines that grew it. ``--write-baseline`` rewrites every entry to the
current size; it is for lowering, and for the one commit that raises.

A tracked instruction file with no entry fails as well: a new file is not a way
round the budget. A file that is not tracked (``CLAUDE.md`` is a private,
per-checkout file in some trees) is not measured.

Standard library only: it runs on the host, where ``make lint`` lives.

    python3 backend/scripts/check_agents_md_budget.py [--write-baseline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BASELINE = Path(__file__).with_name('agents-md-budget.json')

FILES = ('AGENTS.md', 'backend/AGENTS.md', 'frontend/AGENTS.md', 'CLAUDE.md')


def _tracked_sizes() -> dict[str, int]:
    names = set(
        subprocess.run(
            ['git', 'ls-files', '-z', '--', *FILES],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split('\0')
    )
    return {
        name: (_ROOT / name).stat().st_size
        for name in FILES
        if name in names and (_ROOT / name).is_file()
    }


def verdicts(sizes: dict[str, int], limits: dict[str, int]) -> list[str]:
    """One message per file that is over its limit or has none."""
    problems = []
    for name, size in sorted(sizes.items()):
        if name not in limits:
            problems.append(
                f'{name} ({size} bytes) has no entry in {_BASELINE.name} — '
                'a new instruction file needs one, in a commit of its own'
            )
        elif size > limits[name]:
            problems.append(
                f'{name} is {size} bytes, {size - limits[name]} over its '
                f'{limits[name]}. Trim it, or raise the entry in a commit of its '
                'own that says what was added and why'
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--write-baseline', action='store_true')
    args = parser.parse_args()

    sizes = _tracked_sizes()
    if 'AGENTS.md' not in sizes:
        print('check_agents_md_budget: AGENTS.md not found — wrong working tree?')
        return 2
    if args.write_baseline:
        head = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _BASELINE.write_text(
            json.dumps(
                {
                    'unit': 'bytes',
                    'measured_on': head,
                    'limits': dict(sorted(sizes.items())),
                },
                indent=2,
            )
            + '\n',
            encoding='utf-8',
        )
        print(f'wrote {_BASELINE.name}: {sizes}')
        return 0

    limits = json.loads(_BASELINE.read_text(encoding='utf-8'))['limits']
    problems = verdicts(sizes, limits)
    for problem in problems:
        print(f'FAIL: {problem}')
    if problems:
        return 1
    print(
        'agent instruction files: '
        + ', '.join(f'{n} {s}/{limits[n]}' for n, s in sorted(sizes.items()))
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
