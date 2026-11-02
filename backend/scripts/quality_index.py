#!/usr/bin/env python3
"""
Inventari Quality Index — automated code health score.

Purely automated metrics. No manual bug counts.
Track the trend, not the absolute number. Target: never go down.

Usage:
    make quality-index
    docker compose exec backend uv run python scripts/quality_index.py
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path('app')
MODULES_DIR = APP_DIR / 'modules'

RUFF_PENALTY_PER = 0.5
MYPY_PENALTY_PER = 0.3
TWIN_PENALTY_PER = 0.1
TOCTOU_PENALTY_PER = 0.01
TODO_PENALTY_PER = 0.5
LONG_FUNC_PENALTY_PER = 0.02


@dataclass
class Metrics:
    ruff_violations: int = 0
    mypy_errors: int = 0
    todo_markers: int = 0
    long_functions: int = 0
    sync_async_twins: int = 0
    toctou_risk_functions: int = 0


def count_long_functions(directory: Path, threshold: int = 50) -> int:
    count = 0
    for root, _, files in os.walk(directory):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(Path(path).read_text())
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, 'end_lineno'):
                        if (
                            node.end_lineno is not None
                            and node.end_lineno - node.lineno + 1 > threshold
                        ):
                            count += 1
    return count


def count_sync_async_twins(directory: Path) -> int:
    twin_count = 0
    for root, _, files in os.walk(directory):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(Path(path).read_text())
            except (OSError, SyntaxError, ValueError):
                continue
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
            for n in names:
                base = n
                for suffix in ('_async', '_sync'):
                    if n.endswith(suffix) and len(n) > len(suffix):
                        base = n[: -len(suffix)]
                        break
                if base != n and base in names:
                    twin_count += 1
    return twin_count


# ──── TOCTOU DETECTION ────────────────────────────────────────────────────────

_LOCK_PATTERNS = ('with_for_update', 'pg_advisory_xact_lock')
_TEST_PATTERNS = ('/tests/', 'tests/integration', 'tests/unit', 'test_')
_ADMIN_NAME_PATTERNS = (
    'seed_',
    'cleanup_',
    'deduplicate_',
    'purge_',
    '_migrate',
    'migrate_',
)


def _strip_comments(src: str) -> str:
    lines = src.split('\n')
    cleaned = []
    for line in lines:
        ci = line.find('#')
        if ci >= 0:
            in_str, sc = False, None
            for i, c in enumerate(line):
                if c in '"\'' and (i == 0 or line[i - 1] != '\\'):
                    if not in_str:
                        in_str, sc = True, c
                    elif c == sc:
                        in_str = False
            if not in_str:
                line = line[:ci] + ' ' * (len(line) - ci)
        cleaned.append(line)
    return '\n'.join(cleaned)


def _has_select(t: str) -> bool:
    return re.search(r'\bselect\s*\(', t) is not None


def _has_mutation(t: str) -> bool:
    return bool(
        re.search(
            r'\bdb\.add\s*\(|\bdb\.delete\s*\(|\bsetattr\s*\(|\.status\s*=\s*[^=]|\.quantity\s*=\s*[^=]',
            t,
        )
    )


def _has_lock(t: str) -> bool:
    return any(p in t for p in _LOCK_PATTERNS)


def _is_test(rel: str) -> bool:
    return any(p in rel for p in _TEST_PATTERNS)


def _is_delete_pk(t: str) -> bool:
    pk = bool(re.search(r'select\s*\(\s*\w+\s*\)\s*\.where\s*\(\s*\w+\.id\s*==', t))
    return pk and 'db.delete(' in t and 'db.add(' not in t


def _is_state_machine(t: str) -> bool:
    guard = bool(re.search(r'\.status\s*(?:==|!=)\s*[\'\"]\w+[\'\"]', t))
    terminal = bool(
        re.search(
            r'\.status\s*=\s*[\'\"](?:cancelled|completed|archived|deleted|skipped)', t
        )
    )
    if not (guard and terminal):
        return False
    return not bool(re.search(r'\bdb\.add\s*\(|event_bus\.|notify_|\.emit\s*\(', t))


def _is_admin(name: str) -> bool:
    return any(p in name.lower() for p in _ADMIN_NAME_PATTERNS)


def count_toctou_risk(directory: Path) -> int:
    count = 0
    for root, _, fl in os.walk(directory):
        for f in fl:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            if _is_test(os.path.relpath(path, '.')):
                continue
            try:
                src, tree = Path(path).read_text(), ast.parse(Path(path).read_text())
            except (OSError, SyntaxError, ValueError):
                continue
            lines = _strip_comments(src).split('\n')
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) or not hasattr(node, 'end_lineno'):
                    continue
                ft = '\n'.join(lines[node.lineno - 1 : node.end_lineno])
                if not (_has_select(ft) and _has_mutation(ft)):
                    continue
                if (
                    _has_lock(ft)
                    or _is_delete_pk(ft)
                    or _is_state_machine(ft)
                    or _is_admin(node.name)
                ):
                    continue
                count += 1
    return count


def run_cmd(cmd: list[str]) -> str:
    try:
        return (
            subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
            + subprocess.run(cmd, capture_output=True, text=True, timeout=60).stderr
        )
    except (OSError, subprocess.SubprocessError):
        return ''


def collect() -> Metrics:
    m = Metrics()
    m.ruff_violations = len(
        [
            line
            for line in run_cmd(['uv', 'run', 'ruff', 'check', '--statistics'])
            .strip()
            .split('\n')
            if line.strip()
        ]
    )
    m.mypy_errors = run_cmd(
        ['uv', 'run', 'mypy', str(APP_DIR), '--no-error-summary']
    ).count('error:')
    tc = 0
    for root, _, files in os.walk(APP_DIR):
        for f in files:
            if f.endswith('.py'):
                tc += len(
                    re.findall(
                        r'\b(TODO|FIXME|HACK|XXX)\b',
                        Path(os.path.join(root, f)).read_text(),
                    )
                )
    m.todo_markers = tc
    m.long_functions = count_long_functions(APP_DIR)
    m.sync_async_twins = count_sync_async_twins(APP_DIR)
    m.toctou_risk_functions = count_toctou_risk(MODULES_DIR)
    return m


def score(m: Metrics) -> tuple[float, dict[str, float]]:
    p = {
        'ruff': m.ruff_violations * RUFF_PENALTY_PER,
        'mypy': m.mypy_errors * MYPY_PENALTY_PER,
        'todo': m.todo_markers * TODO_PENALTY_PER,
        'long_funcs': m.long_functions * LONG_FUNC_PENALTY_PER,
        'sync_async_twins': m.sync_async_twins * TWIN_PENALTY_PER,
        'toctou_risk': m.toctou_risk_functions * TOCTOU_PENALTY_PER,
    }
    return max(0.0, 100.0 - sum(p.values())), p


def main() -> None:
    print('Collecting metrics...')
    m = collect()
    s, br = score(m)
    print(f'\n{"=" * 60}')
    print(f'  QUALITY INDEX: {s:.1f} / 100')
    print(f'{"=" * 60}\n')
    print(f'  Ruff violations:  {m.ruff_violations:>8,}')
    print(f'  Mypy errors:      {m.mypy_errors:>8,}')
    print(f'  TODO/FIXME:       {m.todo_markers:>8,}')
    print(f'  Long funcs (>50): {m.long_functions:>8,}')
    print(f'  Sync/async twins: {m.sync_async_twins:>8,}')
    print(f'  TOCTOU risk:      {m.toctou_risk_functions:>8,}')
    print('\n  Penalties:')
    for k, v in sorted(br.items(), key=lambda x: -x[1]):
        if v > 0:
            print(f'    {k:<20s} -{v:.1f}')
    print(f'    {"TOTAL":<20s} -{sum(br.values()):.1f}')
    print(f'\n  Track weekly. Target: never go down.\n{"=" * 60}\n')
    print(
        f'CSV: {s:.1f},{m.ruff_violations},{m.mypy_errors},{m.todo_markers},{m.long_functions},{m.sync_async_twins},{m.toctou_risk_functions}'
    )


if __name__ == '__main__':
    main()
