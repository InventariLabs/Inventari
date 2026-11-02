"""The Node and Python floors are one number wherever a reader looks for them.

Four places state what a machine needs to run this project: `engines` in
`frontend/package.json`, CONTRIBUTING.md's prerequisites, the Docker images
that actually build it, and the workflow that gates a push. They are copies of
one decision, and copies drift — `package.json` carried no `engines` field at
all while every image and the workflow already ran Node 26, so nothing told a
contributor or a package manager what the rest of the repository required.

The floors are read out of the files themselves: a bump applied in one place
and missed in the others fails here, on the branch that half-made it, instead
of in somebody's container or a contributor's shell.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The checkout. `docker-compose.yml` mounts it at `/repo` and names it in
#: `INVENTARI_REPO_ROOT`; on the host it is three levels above this file.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: Every file that states a floor, and the pattern each states it with.
_NODE_SOURCES = {
    'frontend/Dockerfile': r'^FROM node:(\d+)',
    'frontend/Dockerfile.dev': r'^FROM node:(\d+)',
    '.github/workflows': r"node-version: '(\d+)'",
    'CONTRIBUTING.md': r'Node\.js (\d+)\+',
}

_PYTHON_SOURCES = {
    'backend/pyproject.toml': r'requires-python = ">=(\d+\.\d+)',
    'backend/Dockerfile': r'^FROM python:(\d+\.\d+)',
    '.github/workflows': r'uv python install (\d+\.\d+)',
    'CONTRIBUTING.md': r'Python (\d+\.\d+)\+',
}


def _files(source: str) -> list[Path]:
    """The files one entry of a floor table stands for — a directory is every
    workflow, because a workflow is one place a reader copies the number into."""
    path = _REPO_ROOT / source
    if path.is_dir():
        return sorted(path.glob('*.yml')) + sorted(path.glob('*.yaml'))
    return [path]


def _floors(sources: dict[str, str]) -> dict[str, set[str]]:
    """Every value each source states, keyed by the source's name."""
    found: dict[str, set[str]] = {}
    for source, pattern in sources.items():
        for file in _files(source):
            assert file.is_file(), f'{source} is not reachable from here'
            text = file.read_text(encoding='utf-8')
            values = set(re.findall(pattern, text, re.M))
            found.setdefault(source, set()).update(values)
    return found


def _declared_node_floor() -> str:
    """The major version `engines.node` promises, e.g. `>=26` -> `26`."""
    package = json.loads(
        (_REPO_ROOT / 'frontend/package.json').read_text(encoding='utf-8')
    )
    engines = package.get('engines')
    assert isinstance(engines, dict) and engines.get('node'), (
        'frontend/package.json declares no engines.node: npm, nvm and every'
        ' editor reading the field are left to guess what the Dockerfiles know.'
    )
    match = re.search(r'(\d+)', str(engines['node']))
    assert match, f'engines.node {engines["node"]!r} does not name a version'
    return match.group(1)


def test_every_source_states_a_node_floor() -> None:
    """A source that states nothing cannot agree with the rest — that is how a
    floor goes missing from one file while the others keep it."""
    floors = _floors(_NODE_SOURCES)
    for source, values in floors.items():
        assert values, f'{source} states no Node version'

    declared = _declared_node_floor()
    assert declared, 'engines.node states no version'


def test_the_node_floor_is_the_same_everywhere() -> None:
    """One floor: `engines.node`, both frontend images, every workflow and the
    prerequisites a contributor reads before they start."""
    floors = _floors(_NODE_SOURCES)
    declared = _declared_node_floor()
    all_values = set().union(*floors.values())
    all_values.add(declared)

    assert len(all_values) == 1, (
        'Node floor differs between the sources: '
        f'{floors} and engines.node={declared!r}. One number, or a '
        'contributor installs what one file asks for and runs what another does.'
    )


def test_every_source_states_a_python_floor() -> None:
    floors = _floors(_PYTHON_SOURCES)
    for source, values in floors.items():
        assert values, f'{source} states no Python version'


def test_the_python_floor_is_the_same_everywhere() -> None:
    """`requires-python`, the backend image, every workflow and the
    prerequisites — the same number in all four."""
    floors = _floors(_PYTHON_SOURCES)
    all_values = set().union(*floors.values())

    assert len(all_values) == 1, f'Python floor differs between the sources: {floors}'
