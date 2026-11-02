"""The production image installs the runtime dependencies and none of the dev tooling.

The tools that test, lint and type-check the code sit in the ``dev`` dependency
group. Two things keep them out of the image, and either can be undone by an
innocent-looking edit: a tool moved into ``dependencies`` (or pulled in by a
runtime dependency), and the image build dropping ``--no-dev`` from its export.
"""

import re
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _name(raw: str) -> str:
    return re.sub(r'[-_.]+', '-', raw).lower()


def _requirement_name(requirement: str) -> str:
    return _name(re.split(r'[\s\[<>=!~;(]', requirement.strip(), maxsplit=1)[0])


def _pyproject() -> dict:
    return tomllib.loads((BACKEND / 'pyproject.toml').read_text())


def _dev_group() -> set[str]:
    return {_requirement_name(r) for r in _pyproject()['dependency-groups']['dev']}


def _production_closure() -> set[str]:
    """Every package the lock reaches from the project's runtime dependencies."""
    lock = tomllib.loads((BACKEND / 'uv.lock').read_text())
    packages = {_name(p['name']): p for p in lock['package']}
    project = _name(_pyproject()['project']['name'])
    seen: set[str] = set()
    todo = [_name(d['name']) for d in packages[project].get('dependencies', [])]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(_name(d['name']) for d in packages[name].get('dependencies', []))
    return seen


@pytest.mark.unit
class TestProductionImageCarriesNoDevTools:
    def test_the_tools_the_audit_named_are_in_the_dev_group(self):
        group = _dev_group()
        for tool in ('pytest', 'ruff', 'mypy', 'pre-commit', 'vulture'):
            assert tool in group, f'{tool} must be declared in the dev group'

    def test_no_dev_tool_is_a_runtime_dependency(self):
        runtime = {
            _requirement_name(r) for r in _pyproject()['project']['dependencies']
        }
        assert sorted(runtime & _dev_group()) == []

    def test_no_runtime_dependency_pulls_a_dev_tool_in(self):
        # A transitive requirement lands in the image just as a direct one does.
        assert sorted(_production_closure() & _dev_group()) == []

    def test_the_image_build_exports_without_the_dev_group(self):
        dockerfile = (BACKEND / 'Dockerfile').read_text()
        export = [line for line in dockerfile.splitlines() if 'uv export' in line]
        assert export, 'the Dockerfile no longer exports the locked requirements'
        assert all('--no-dev' in line for line in export)
