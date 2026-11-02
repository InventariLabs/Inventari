"""Enabling a module checks its requirements as a graph, not as a list.

``_check_module_dependencies`` walked the requirements with one set of every
module it had seen and refused a module met twice as a cycle. A shared
prerequisite — ``root`` needs ``left`` and ``right``, and both need
``shared`` — is met twice without any loop, so a valid module could not be
switched on. Only a module that is its own ancestor is a cycle.
"""

from __future__ import annotations

import pytest

from app.api import modules as modules_api
from app.core.exceptions import ServiceRejectionError


class _Meta:
    def __init__(self, requires: list[str]) -> None:
        self.requires = requires


class _Module:
    def __init__(self, requires: list[str]) -> None:
        self.metadata = _Meta(requires)


def _graph(monkeypatch: pytest.MonkeyPatch, requires: dict[str, list[str]]) -> None:
    monkeypatch.setattr(
        modules_api.module_registry,
        'get',
        lambda name: _Module(requires[name]) if name in requires else None,
    )
    monkeypatch.setattr(modules_api, 'is_always_on', lambda name: False)


def test_a_shared_prerequisite_of_two_branches_is_not_a_cycle(monkeypatch) -> None:
    _graph(
        monkeypatch,
        {
            'root': ['left', 'right'],
            'left': ['shared'],
            'right': ['shared'],
            'shared': [],
        },
    )

    modules_api._check_module_dependencies('root', ['root', 'left', 'right', 'shared'])


def test_a_directed_cycle_deeper_in_the_graph_is_still_refused(monkeypatch) -> None:
    _graph(
        monkeypatch,
        {'root': ['left'], 'left': ['shared'], 'shared': ['left']},
    )

    with pytest.raises(ServiceRejectionError) as refused:
        modules_api._check_module_dependencies('root', ['root', 'left', 'shared'])

    assert refused.value.code == 'MODULE_DEPENDENCY_CYCLE'


def test_a_diamond_beside_a_cycle_still_reports_the_cycle(monkeypatch) -> None:
    _graph(
        monkeypatch,
        {
            'root': ['left', 'right'],
            'left': ['shared'],
            'right': ['shared'],
            'shared': ['root'],
        },
    )

    with pytest.raises(ServiceRejectionError) as refused:
        modules_api._check_module_dependencies(
            'root', ['root', 'left', 'right', 'shared']
        )

    assert refused.value.code == 'MODULE_DEPENDENCY_CYCLE'
