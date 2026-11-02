"""The dev frontend installs from the lockfile, never through it.

The startup command of ``frontend/Dockerfile.dev`` runs against the bind
mount — the host's own ``frontend`` tree — so an ``npm install`` there that
finds a gap between ``package.json`` and ``package-lock.json`` writes the
missing lines into a **tracked** file. One such drift was fixed by
regenerating the lock; the command that caused it was still in place, ready
to cause the next one, which is why the symptom came back as a theory
(2026-08-29).

``npm ci`` cannot write the lock. On a drift it refuses with an error that
names the two files, the container stops instead of starting, and `git
status` after ``make dev-up`` stays clean — a signal rather than a dirty
tree.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_DOCKERFILE = _REPO_ROOT / 'frontend' / 'Dockerfile.dev'


def _lines() -> list[str]:
    return _DOCKERFILE.read_text().splitlines()


def test_the_startup_command_installs_with_npm_ci() -> None:
    cmd = next(line for line in _lines() if line.startswith('CMD '))
    assert 'npm ci' in cmd, (
        f'the container starts with an install that can rewrite the lock: {cmd}'
    )
    assert 'npm install' not in cmd


def test_the_build_layer_installs_with_npm_ci() -> None:
    runs = [line for line in _lines() if line.startswith('RUN ')]
    assert runs, 'the Dockerfile installs nothing at build time'
    offenders = [line for line in runs if 'npm install' in line]
    assert not offenders, f'a build step still installs through the lock: {offenders}'


def test_a_drift_is_named_where_it_is_refused() -> None:
    """The refusal has to say what to do, or the reader gets an npm usage dump.

    A container that dies on startup is only a signal if the line it dies on
    names the file that has to be regenerated — on the host, where the lock
    lives.
    """
    cmd = next(line for line in _lines() if line.startswith('CMD '))
    assert 'package-lock.json' in cmd
    assert 'out of sync' in cmd


def test_a_changed_manifest_reaches_the_installer() -> None:
    """A stale lock arrives as a moved package.json, and only as that.

    The install runs when `node_modules` is missing or a manifest is newer
    than it. Testing only the lock misses the whole case this exists for:
    package.json gains a dependency, the lock does not follow, and node_modules
    is younger than both — the install would be skipped, the drift would sail
    through, and the container would start on a tree that is missing a
    package. Both manifests have to be able to trigger it.
    """
    cmd = next(line for line in _lines() if line.startswith('CMD '))
    assert 'package.json -nt node_modules' in cmd
    assert 'package-lock.json -nt node_modules' in cmd
