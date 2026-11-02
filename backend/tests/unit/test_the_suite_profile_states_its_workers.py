"""The suite profiler, held to the worker count its report states.

``scripts/profile_suite.py`` exists so that a timing claim carries the
conditions it was measured under. It used to run pytest with ``-n auto`` —
every core of the host, which the suite's own rule forbids on a shared
machine — and then wrote the CPU count into the report as the worker count,
and worker-time as wall x CPUs. Once the worker count is a choice, those two
numbers have to follow the choice, or the report states a machine it did not
run on.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_PROFILER = Path(__file__).resolve().parents[2] / 'scripts' / 'profile_suite.py'

_OUTPUT = '\n'.join(
    [
        '0.60s setup    tests/unit/test_a.py::test_one',
        '0.20s call     tests/unit/test_a.py::test_one',
        '0.20s teardown tests/unit/test_b.py::test_two',
        '======= 2 passed in 3.00s =======',
    ]
)


def _profiler() -> Any:
    spec = importlib.util.spec_from_file_location('profile_suite', _PROFILER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _commands(monkeypatch: pytest.MonkeyPatch, profiler: Any) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> SimpleNamespace:
        seen.append(cmd)
        return SimpleNamespace(stdout=_OUTPUT, stderr='', returncode=0)

    monkeypatch.setattr(profiler.subprocess, 'run', fake_run)
    return seen


def _run_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiler: Any, *argv: str
) -> dict:
    monkeypatch.setattr(profiler, '_REPORT_DIR', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['profile_suite.py', *argv])
    assert profiler.main() == 0
    (report,) = tmp_path.glob('*.json')
    return json.loads(report.read_text())


def test_the_default_run_takes_twelve_workers_not_every_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profiler = _profiler()
    commands = _commands(monkeypatch, profiler)

    _run_main(monkeypatch, tmp_path, profiler)

    (cmd,) = commands
    assert cmd[cmd.index('-n') + 1] == '12'
    assert 'auto' not in cmd


def test_the_report_states_the_workers_it_ran_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profiler = _profiler()
    commands = _commands(monkeypatch, profiler)
    # Swapped in the profiler's namespace only — patching the real modules
    # would hand the fake clock to pytest itself.
    monkeypatch.setattr(profiler, 'os', SimpleNamespace(cpu_count=lambda: 24))
    monkeypatch.setattr(
        profiler, 'time', SimpleNamespace(perf_counter=iter([0.0, 10.0]).__next__)
    )

    report = _run_main(monkeypatch, tmp_path, profiler, '--workers', '4')

    (cmd,) = commands
    assert cmd[cmd.index('-n') + 1] == '4'
    assert report['machine']['workers'] == 4
    assert report['machine']['cpus'] == 24
    # Worker-time is what the workers could have spent: wall x 4, not x 24.
    assert report['worker_seconds'] == 40.0
    assert report['unaccounted_pct'] == 97.5
