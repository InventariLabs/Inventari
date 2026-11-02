"""Fail when a file under ``app/`` imports a package pyproject does not declare.

``cryptography`` encrypts the secrets an organization stores and verifies
module signatures, and nothing in ``pyproject.toml`` named it: it reached the
tree as google-auth's transitive requirement, so a reader of the dependency
list saw no requirement for the library whose absence breaks secret
decryption and signature verification at import time. The same scan found
``rich``, ``starlette``, ``markupsafe`` and ``botocore`` imported directly
while arriving through typer, fastapi, jinja2 and aioboto3. This gate keeps
the next one from waiting for an audit.

The question it answers is not "is it installed" — a transitive requirement
installs a package, and always will — but "does a *declared* dependency own
the top-level package this file imports". So it reads the dependency names
out of ``pyproject.toml`` and asks the installed environment, through
``importlib.metadata``, which distribution owns each top-level name. It has
to run inside the backend environment, where that mapping exists.

The suite's own files live under ``app/`` beside the code they cover, importing
pytest and pypdf there, so they may import anything the file declares —
``[project].dependencies`` and the dependency groups. Every other file ships in
the production image, which is built with ``uv export --frozen --no-dev``: it
may import ``[project].dependencies`` only, or it fails at start on a package
the image does not have.

A top-level name that resolves to a file or directory next to ``pyproject.toml``
(``seed_demo_data``, ``shell``) is a module of this repository, not a package.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from collections import defaultdict
from importlib import metadata
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PYPROJECT = BACKEND_DIR / 'pyproject.toml'
APP_DIR = BACKEND_DIR / 'app'
STDLIB = frozenset(sys.stdlib_module_names)
# The one file outside a ``tests/`` directory that belongs to the suite: the pytest
# plugin modules load into their own test runs.
TEST_SUPPORT_FILES = frozenset({'app/core/module_test_plugin.py'})


def _normalise(name: str) -> str:
    """PEP 503: ``PyJWT`` and ``pyjwt`` are one distribution, spelled once."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _requirement_name(requirement: str) -> str:
    """``typer[all]>=0.27.1`` → ``typer``: the name ends at the first marker."""
    match = re.match(r'[A-Za-z0-9][A-Za-z0-9._-]*', requirement.strip())
    if match is None:  # a requirement is written as words or not at all
        raise ValueError(f'cannot read a distribution name from {requirement!r}')
    return match.group(0)


def is_test_file(relative: str) -> bool:
    """Whether a path (relative to ``backend/``) belongs to the suite, not the image."""
    path = Path(relative)
    return (
        'tests' in path.parts
        or path.name == 'conftest.py'
        or relative in TEST_SUPPORT_FILES
    )


def declared_distributions(
    pyproject: Path = PYPROJECT, *, runtime_only: bool = False
) -> set[str]:
    """Every distribution the file declares, extras and pins stripped.

    ``runtime_only`` leaves the dependency groups out: what the production image has.
    """
    data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    raw = list(data['project']['dependencies'])
    if not runtime_only:
        for group in data.get('dependency-groups', {}).values():
            raw.extend(dep for dep in group if isinstance(dep, str))
    return {_normalise(_requirement_name(dep)) for dep in raw}


def imported_top_levels(
    app_dir: Path = APP_DIR, *, tests: bool | None = None
) -> dict[str, list[str]]:
    """Absolute top-level names imported under ``app_dir``, with their files.

    ``tests`` narrows the scan to the suite's files (``True``) or to the files that
    ship in the image (``False``); ``None`` reads both.

    Relative imports resolve against the importing file and are no dependency
    of the package; ``app`` and its submodules are the repository's own.
    """
    found: dict[str, list[str]] = defaultdict(list)
    for path in sorted(app_dir.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        relative = str(path.relative_to(app_dir.parent))
        if tests is not None and is_test_file(relative) != tests:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [] if node.level or node.module is None else [node.module]
            else:
                continue
            for name in names:
                found[name.split('.')[0]].append(relative)
    return dict(found)


def undeclared_imports(
    imported: dict[str, list[str]],
    declared: set[str],
    owners: dict[str, set[str]],
    backend_dir: Path = BACKEND_DIR,
) -> list[str]:
    """The top-level names nothing declared provides, each with its files.

    ``owners`` maps a top-level name to the normalised names of the
    distributions that installed it, which is how ``cryptography`` (a
    requirement of google-auth) is told apart from ``cryptography`` declared
    on its own: only the declared set makes the intersection non-empty.
    """
    problems = []
    for name, files in sorted(imported.items()):
        if name in STDLIB:  # no requirement to write for what ships with Python
            continue
        if owners.get(name, set()) & declared:
            continue
        if (backend_dir / f'{name}.py').is_file() or (backend_dir / name).is_dir():
            continue  # a module of this repository, on sys.path beside pyproject.toml
        problems.append(f'{name} ({", ".join(sorted(set(files)))})')
    return problems


def installed_owners() -> dict[str, set[str]]:
    """Which distributions own each top-level name, in this environment."""
    return {
        top: {_normalise(dist) for dist in dists if dist}
        for top, dists in metadata.packages_distributions().items()
    }


def main() -> int:
    owners = installed_owners()
    imported = imported_top_levels()
    problems = undeclared_imports(
        imported_top_levels(tests=True), declared_distributions(), owners
    ) + undeclared_imports(
        imported_top_levels(tests=False),
        declared_distributions(runtime_only=True),
        owners,
    )
    if problems:
        print(
            'Undeclared imports under app/ — no dependency declared in '
            'pyproject.toml provides them (outside tests only [project].dependencies '
            'counts: the production image has no dependency group):\n  '
            + '\n  '.join(problems),
            file=sys.stderr,
        )
        return 1
    print(
        f'{len(imported)} top-level names imported under app/, '
        'each owned by a declared dependency.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
