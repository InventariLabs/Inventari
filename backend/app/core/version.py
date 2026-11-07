"""Platform version access and semver comparison.

The version SSOT is ``backend/pyproject.toml`` (``[project].version``),
mirrored by the README and ``frontend/package.json``; ``app/main.py`` and
the About screen read it from here. ``importlib.metadata`` is deliberately
NOT used — installed dist metadata goes stale in long-lived containers.
"""

from __future__ import annotations

import re
import tomllib
from functools import cache
from pathlib import Path

from app.core.operator_error import OperatorError

_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / 'pyproject.toml'

_VERSION_RE = re.compile(r'^\d+(?:\.\d+){0,2}$')


@cache
def _project_field(name: str) -> str | None:
    try:
        data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding='utf-8'))
        return str(data['project'][name])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return None


def get_platform_version() -> str:
    """Return the platform version from pyproject.toml ('0.0.0' on failure)."""
    return _project_field('version') or '0.0.0'


def get_platform_license() -> str:
    """Return the SPDX licence identifier pyproject.toml declares."""
    return _project_field('license') or 'AGPL-3.0-only'


def parse_version(text: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' (or shorter) into a comparable tuple. Raises ValueError."""
    stripped = text.strip()
    if not _VERSION_RE.match(stripped):
        raise OperatorError(f'Invalid version string: {text!r} (expected X.Y.Z)')
    parts = [int(p) for p in stripped.split('.')]
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def check_min_version(
    min_version: str, platform_version: str | None = None
) -> str | None:
    """Return an error message when the platform doesn't meet *min_version*.

    Empty/blank *min_version* means no constraint (``None``). Invalid
    version strings are treated as unmet (safe default).
    """
    if not min_version or not min_version.strip():
        return None
    platform = (
        platform_version if platform_version is not None else get_platform_version()
    )
    try:
        required = parse_version(min_version)
        current = parse_version(platform)
    except ValueError as exc:
        return str(exc)
    if current < required:
        return f'requires Inventari >= {min_version}, current version is {platform}'
    return None
