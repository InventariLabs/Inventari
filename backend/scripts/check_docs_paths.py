#!/usr/bin/env python3
"""Drift gate: file paths referenced in public docs must exist.

Public documentation (README, AGENTS, the module guides, ``docs/**``) is a
contract with the reader — a path in backticks is a promise that the file is
there. This script parses inline-code spans from the tracked public docs and
asserts each repo-relative path resolves in the working tree.

Scope decisions:
- Only spans that look like paths are checked: they contain ``/`` and carry a
  plausible extension, or they name a known root-level file (``manage.py``,
  ``Makefile``, ...). Bare identifiers (``module.py``, ``CoreAPI``) are prose,
  not paths.
- Didactic placeholders (``my_module``, ``your-domain.com``) and glob
  patterns are allowlisted below — keep the list short and commented.
- Historical annotations in ADRs are skipped when the line carries an explicit
  marker (``(removed since)``, ``(today: ...)``): the ADR is a record of what
  was true when written, and the marker says so.

WHY THIS IS A SCRIPT AND NOT ONLY A TEST. It used to live solely in
``backend/tests/integration/test_docs_paths_drift.py``, which skipped whenever
the docs directory was not mounted — and it was not mounted in the containers
everybody actually works in. The suite therefore reported green by skipping,
while the check itself had been red on ``dev`` for a long stretch: five broken
references nobody could see, because the only place the colour showed was a CI
run, and CI ran on ``main`` alone. A gate whose red is unreachable is not a
gate. Run from ``make lint`` on the host, where the checkout is complete, it
is read in the loop people work in; the test stays so the CI run keeps it too,
and ``docker-compose.yml`` now mounts these documents into the backend
container so the test measures them there as well instead of skipping.

Those two readers must see the same input, or the container's green means less
than it looks like. ``_REQUIRED`` below is what stops a partial mount from
shrinking the check quietly: a document this tree cannot see is a failure, not
a smaller scan.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Two parents above this file is the repository root in a checkout. Inside the
# backend container the file sits at /app/scripts/, so that arithmetic lands on
# `/` — which holds none of the checkout. docker-compose.yml mounts the
# repository read-only and names it, so the readers can be pointed at the same
# tree the host and CI read.
_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[2]
)

# Directories under docs/ that are gitignored and never reach the repository.
_DOCS_EXCLUDED_DIRS = {'business', 'marketing', 'plans', 'reviews', 'superpowers', 'ux'}

_ROOT_DOCS = [
    'README.md',
    'AGENTS.md',
    'backend/AGENTS.md',
    'frontend/AGENTS.md',
    'CHANGELOG.md',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'MODULES_GUIDE.md',
    'MODULE_QUICKSTART.md',
    'frontend/UI_GUIDELINES.md',
]

# Every document above is tracked, so one that is missing means the tree this
# is reading is not the tree it claims to be — a partial checkout, or a
# container that mounts some of these and not others. Either way the check must
# say so rather than scan the rest and report success: a gate that shrinks its
# own input is the failure this script was extracted to fix.
_REQUIRED = tuple(_ROOT_DOCS) + ('docs',)

# A span is a candidate path when it contains a slash and ends in a known
# extension, or starts with a known top-level directory.
_KNOWN_EXTENSION = re.compile(
    r'\.(py|pyi|ts|tsx|js|mjs|jsx|md|json|ya?ml|toml|sh|sql|env|example|txt|cfg|ini|html|css|csv)$'
)
_KNOWN_TOP_DIR = re.compile(
    r'^(backend|frontend|docs|scripts|migrations|load_tests|print-agent|\.github)/'
)
# Docs refer to backend files as `app/...` and to frontend files as `src/...`
# — a span resolves when it exists under ANY of these prefixes. The module
# roots are a pair on purpose: a subsystem guide names a backend module file
# the same shorthand way it names a frontend one (`approvals/_services.py`),
# and for a long time only the frontend half of that pair was here.
_RESOLVE_ROOTS = (
    '',
    'backend/',
    'backend/app/',
    'backend/app/modules/',
    'frontend/',
    'frontend/src/',
    'frontend/src/modules/',
)

# Trailing `:12` / `:12-34` line references are not part of the path.
_LINE_SUFFIX = re.compile(r':\d+(-\d+)?$')

# Didactic placeholders and examples that are not real paths. Keep commented.
_ALLOWLIST = {
    'app/modules/<M>/migrations/versions/',  # per-module placeholder
    'docs/api/openapi.json',  # generated artifact, freshness-guarded by make check-openapi-fresh
    'backend/data/community_modules.json',  # runtime deployment state, gitignored (app/core/module_tracking.py)
    'backend/community_modules.json',  # legacy runtime path, still read once (app/core/module_tracking.py)
    'load_tests/users.csv',  # written by load_tests/prepare.sh, gitignored: it holds the shared password
    # Dependency trees an install creates, never tracked: CI's backend job has no frontend install
    'backend/.venv',
    'frontend/node_modules',
    'backend/uploads',  # created by the app at runtime on a host with no /app, gitignored
    'frontend/dist/',  # the production build's output, gitignored; a fresh checkout has none
}

# Spans containing any of these fragments are examples, not references.
_ALLOWLIST_FRAGMENTS = (
    'my_module',
    'my_feature',
    'warranty_tracker',  # worked example the reader creates in the quickstart
    'IndexPage.tsx',  # module-skeleton illustration
    'useMyModule',  # module-skeleton illustration
    'migrations/versions/001_initial.py',  # module layout illustration
    'weather_widget',
    'your-domain',
    'example.com',
    '<module>',
    '<M>',
)

# A line carrying one of these markers documents history, not current state.
# `- Removed:` lists what an ADR deleted; `(private plan, not published)`
# annotates a reference to the local-only plans/ directory.
_HISTORICAL_MARKER = re.compile(
    r'\(removed since\)|\(today:|no longer exists|not published|^\s*[-*]\s*\*{0,2}removed:',
    re.IGNORECASE,
)

_INLINE_CODE = re.compile(r'`([^`\n]+)`')
# Characters no real path in this repo contains — their presence means the
# span is a command, an expression, or a template.
_NOT_A_PATH = re.compile(r'[\s*<>{}$()|;&"\']|://')


# Directories no document of this repository lives in: dependencies, build output and caches (and every
# dot-directory but `.github`: agent and editor settings are not documents). Only read when git cannot
# enumerate the tracked files (a container that mounts the tree without a usable `.git`).
_WALK_SKIPPED_DIRS = {
    '.git',
    '.venv',
    'node_modules',
    '__pycache__',
    'dist',
    'build',
    'coverage',
    'htmlcov',
    'test-results',
    'playwright-report',
}


def _tracked_markdown() -> list[Path] | None:
    """Every tracked Markdown file, or None when git cannot say."""
    try:
        done = subprocess.run(
            ['git', '-C', str(_ROOT), 'ls-files', '-z', '--', '*.md'],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [n for n in done.stdout.decode('utf-8').split('\0') if n]
    return [_ROOT / n for n in sorted(names)] if names else None


def _walked_markdown() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _WALK_SKIPPED_DIRS
            and (d == '.github' or not d.startswith('.'))
            and not (here == _ROOT / 'docs' and d in _DOCS_EXCLUDED_DIRS)
        )
        # A symlink is a checkout's link to local, untracked material, never a tracked document.
        found += [
            here / f
            for f in sorted(filenames)
            if f.endswith('.md') and not (here / f).is_symlink()
        ]
    return found


def iter_public_docs() -> list[Path]:
    """Every Markdown document of the repository, not a list somebody has to keep.

    A named list left nineteen tracked documents outside the gate, among them the
    tests README and the deployment guide, and a path that rotted in one of them
    passed `make lint`. The tracked files are the public set; the walk is the same
    set read from a tree git cannot see."""
    return _tracked_markdown() or _walked_markdown()


def missing_required() -> list[str]:
    """Documents a complete checkout always has, that this one cannot see."""
    return [rel for rel in _REQUIRED if not (_ROOT / rel).exists()]


def candidate_paths(line: str) -> list[str]:
    out: list[str] = []
    for span in _INLINE_CODE.findall(line):
        span = span.strip()
        if not span or _NOT_A_PATH.search(span):
            continue
        if span.startswith('/') or span.startswith('@/'):
            continue  # URL path or import alias, not a repo path
        span = _LINE_SUFFIX.sub('', span)
        if span in _ALLOWLIST or any(f in span for f in _ALLOWLIST_FRAGMENTS):
            continue
        looks_like_path = '/' in span and (
            _KNOWN_EXTENSION.search(span) or _KNOWN_TOP_DIR.match(span)
        )
        if looks_like_path:
            out.append(span)
    return out


# A path passed to a test runner or an interpreter sits in a fenced command, not
# in an inline span, so the span reader never sees it — and it is the one a
# newcomer copies and runs first.
_COMMAND_LINE = re.compile(r'\b(pytest|vitest|python3?)\b')
_COMMAND_PATH = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+\.(?:py|tsx?))\b')


def command_paths(line: str) -> list[str]:
    if not _COMMAND_LINE.search(line):
        return []
    return [
        m
        for m in _COMMAND_PATH.findall(line)
        if not _NOT_A_PATH.search(m) and not any(f in m for f in _ALLOWLIST_FRAGMENTS)
    ]


# A `file:123` reference is true on the day it is written and false after the
# next edit above it; the reference reader cannot tell. ADRs are exempt: they
# record the code as it was when the decision was taken, and say so.
_LINE_REFERENCE = re.compile(
    r'^[\w./-]+\.(?:py|pyi|ts|tsx|js|mjs|ya?ml|sh|toml):\d+(?:-\d+)?$'
)


def line_references(line: str) -> list[str]:
    return [
        span.strip()
        for span in _INLINE_CODE.findall(line)
        if _LINE_REFERENCE.match(span.strip())
    ]


def exists(span: str) -> bool:
    return any((_ROOT / f'{root}{span}').exists() for root in _RESOLVE_ROOTS)


def find_broken(docs: list[Path] | None = None) -> list[str]:
    """Return ``path:line: `span`` for every reference that does not resolve."""
    broken: list[str] = []
    for doc in docs if docs is not None else iter_public_docs():
        for lineno, line in enumerate(doc.read_text(encoding='utf-8').splitlines(), 1):
            if _HISTORICAL_MARKER.search(line):
                continue
            for span in candidate_paths(line) + command_paths(line):
                if not exists(span):
                    broken.append(f'{doc.relative_to(_ROOT)}:{lineno}: `{span}`')
            if doc.relative_to(_ROOT).parts[:2] != ('docs', 'adr'):
                broken += [
                    f'{doc.relative_to(_ROOT)}:{lineno}: `{span}` (a line number '
                    f'drifts with the next edit; name the function or setting instead)'
                    for span in line_references(line)
                ]
    return broken


FIX_HINT = (
    'Fix the reference, or add a historical marker '
    '(`(removed since)` / `(today: ...)`) if the ADR documents history.'
)


def main() -> int:
    missing = missing_required()
    if missing:
        print(
            'check_docs_paths: this tree is missing public documents the check '
            'reads, so it cannot measure what it claims to:',
            file=sys.stderr,
        )
        for rel in missing:
            print(f'  {rel}', file=sys.stderr)
        print(
            'Run on the host, where the checkout is complete, or set '
            'INVENTARI_REPO_ROOT to it — docker-compose.yml mounts the '
            'repository read-only and names it there for the backend '
            'service. Scanning the rest and reporting success would be the '
            'bug, not the fix.',
            file=sys.stderr,
        )
        return 1

    broken = find_broken(iter_public_docs())
    if broken:
        print('Public docs reference paths that do not exist:', file=sys.stderr)
        for item in broken:
            print(f'  {item}', file=sys.stderr)
        print(FIX_HINT, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
