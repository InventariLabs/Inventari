"""Fail when a module has no purpose card, or a card has lost its boundary.

A purpose card (``docs/purpose/``) is the outside source a screen review reads
before it looks at a screen, so that the goal is not inferred from the fields in
front of it. Without one the review grades each field on whether it is labelled
and constrained, and never asks the question that matters — whether the person
doing this job has any business answering it.

Two failures this catches:

* a module added without a card, which reads to a reviewer as "no boundary
  stated" and quietly turns the review back into a field-by-field pass;
* a card that has kept its headings but emptied out the one that earns it.
  "Deliberately not done" is what separates a boundary from a summary: without
  it every absence looks like a gap, and the review becomes a feature list.

What it deliberately does not check: whether a card is *true*. Nothing here can
tell a boundary that has moved from one that never held. That is what the
review is for.

Runs on the host with the standard library only — ``docs/`` lives above the
backend directory the container mounts.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
MODULES_DIR = BACKEND_DIR / 'app' / 'modules'
FRONTEND_MODULES_DIR = REPO_ROOT / 'frontend' / 'src' / 'modules'
CARDS_DIR = REPO_ROOT / 'docs' / 'purpose'

# The shape, in order. docs/purpose/README.md is the long version.
HEADINGS = (
    'Job',
    'Whose job',
    'Inside the boundary',
    'Outside the boundary',
    'Own concepts / Borrowed',
    'Deliberately not done',
    'Switched off',
)
EARNS_THE_CARD = 'Deliberately not done'

# A frontend directory that is neither a module nor a Core area with a job of its own: shared
# components and hooks, no screen to review. docs/purpose/README.md says so.
NOT_AN_AREA = ('shared',)

WRITE_ONE = (
    'Write one — the shape and the rules are in docs/purpose/README.md. '
    'Seven headings, short; the boundary matters more than the prose.'
)


def _module_names() -> list[str]:
    return sorted(path.parent.name for path in MODULES_DIR.glob('*/manifest.json'))


def _core_areas() -> list[str]:
    """Frontend directories with no backend module behind them: the Core's own areas."""
    if not FRONTEND_MODULES_DIR.is_dir():
        return []
    modules = set(_module_names())
    return sorted(
        path.name
        for path in FRONTEND_MODULES_DIR.iterdir()
        if path.is_dir() and path.name not in modules and path.name not in NOT_AN_AREA
    )


def _sections(card: Path) -> dict[str, str]:
    """Map each ``## `` heading to the text under it."""
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in card.read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            if current is not None:
                sections[current] = '\n'.join(body).strip()
            current = line[3:].strip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = '\n'.join(body).strip()
    return sections


def _check_shape(card: Path, problems: list[str]) -> None:
    found = list(_sections(card))
    relative = card.relative_to(REPO_ROOT)

    missing = [heading for heading in HEADINGS if heading not in found]
    if missing:
        problems.append(f'{relative}: missing heading(s): ' + ', '.join(missing))
        return

    extra = [heading for heading in found if heading not in HEADINGS]
    if extra:
        problems.append(
            f'{relative}: heading(s) outside the shape: ' + ', '.join(extra) + '. '
            'The shape is seven headings "and nothing else" (docs/purpose/README.md).'
        )

    ordered = [heading for heading in found if heading in HEADINGS]
    if ordered != list(HEADINGS):
        problems.append(
            f'{relative}: headings are out of order — a card is read in one '
            'pass, so the order is part of the shape'
        )

    if not _sections(card)[EARNS_THE_CARD]:
        problems.append(
            f'{relative}: "{EARNS_THE_CARD}" is empty. A card without it states '
            'a summary, not a boundary. If the boundary is genuinely not settled '
            'yet, say so there in a sentence.'
        )


def main() -> int:
    if not CARDS_DIR.is_dir():
        print(f'{CARDS_DIR} is missing.', file=sys.stderr)
        return 1

    modules = _module_names()
    if len(modules) < 10:
        print(
            f'Only {len(modules)} modules found under {MODULES_DIR} — this check '
            'is running against the wrong tree.',
            file=sys.stderr,
        )
        return 1

    problems: list[str] = []

    uncarded = [name for name in modules if not (CARDS_DIR / f'{name}.md').is_file()]
    if uncarded:
        problems.append(
            'these modules have no purpose card in docs/purpose/: '
            + ', '.join(uncarded)
            + f'\n{WRITE_ONE}'
        )

    uncarded_areas = [
        name for name in _core_areas() if not (CARDS_DIR / f'core-{name}.md').is_file()
    ]
    if uncarded_areas:
        problems.append(
            'these Core areas (frontend/src/modules/<area>/ with no backend module) have no '
            'card in docs/purpose/: '
            + ', '.join(f'core-{name}.md' for name in uncarded_areas)
            + f'\n{WRITE_ONE}'
        )

    cards = sorted(path for path in CARDS_DIR.glob('*.md') if path.name != 'README.md')
    known = set(modules) | {f'core-{name}' for name in _core_areas()}
    for card in cards:
        if card.stem not in known and FRONTEND_MODULES_DIR.is_dir():
            problems.append(
                f'{card.relative_to(REPO_ROOT)}: no module or Core area of that name — '
                'a card for something that is gone (or renamed) misleads the next review'
            )
    for card in cards:
        _check_shape(card, problems)

    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 1

    print(f'purpose cards: {len(cards)} cards cover {len(modules)} modules.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
