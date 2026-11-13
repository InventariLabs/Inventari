"""The instruction-file budget is a ratchet: growth fails, shrinking passes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        'check_agents_md_budget', _SCRIPTS / 'check_agents_md_budget.py'
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load()


def test_a_file_at_or_under_its_limit_passes() -> None:
    assert (
        gate.verdicts(
            {'AGENTS.md': 100, 'frontend/AGENTS.md': 40},
            {
                'AGENTS.md': 100,
                'frontend/AGENTS.md': 50,
            },
        )
        == []
    )


def test_a_file_one_byte_over_fails_and_says_by_how_much() -> None:
    problems = gate.verdicts({'AGENTS.md': 101}, {'AGENTS.md': 100})
    assert len(problems) == 1
    assert 'AGENTS.md is 101 bytes, 1 over its 100' in problems[0]


def test_a_new_instruction_file_needs_an_entry() -> None:
    problems = gate.verdicts({'CLAUDE.md': 10}, {'AGENTS.md': 100})
    assert len(problems) == 1 and 'CLAUDE.md' in problems[0]


def test_the_committed_baseline_names_every_tracked_instruction_file() -> None:
    raw = json.loads((_SCRIPTS / 'agents-md-budget.json').read_text(encoding='utf-8'))
    assert raw['unit'] == 'bytes' and raw['measured_on']
    assert {'AGENTS.md', 'backend/AGENTS.md', 'frontend/AGENTS.md'} <= set(
        raw['limits']
    )
