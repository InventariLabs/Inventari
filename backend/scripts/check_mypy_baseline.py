from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / 'mypy-baseline.json'
MYPY_COMMAND = [
    sys.executable,
    '-m',
    'mypy',
    'app',
    '--explicit-package-bases',
    '--no-error-summary',
]


def _load_baseline() -> tuple[int, dict[str, int]]:
    data = json.loads(BASELINE_PATH.read_text())
    files = {str(path): int(count) for path, count in data['files'].items()}
    return int(data['total_errors']), files


def _collect_errors(output: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for line in output.splitlines():
        if ': error:' not in line:
            continue
        path = line.split(':', 1)[0]
        counts[path] += 1
    return dict(sorted(counts.items()))


def main() -> int:
    baseline_total, baseline_files = _load_baseline()
    result = subprocess.run(
        MYPY_COMMAND,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    current_files = _collect_errors(result.stdout)
    current_total = sum(current_files.values())

    if result.returncode not in (0, 1):
        print(result.stdout, end='')
        print(f'mypy exited with unexpected status {result.returncode}')
        return result.returncode

    regressions: list[str] = []
    for path, count in current_files.items():
        baseline_count = baseline_files.get(path, 0)
        if count > baseline_count:
            regressions.append(f'{path}: {count} error(s), baseline {baseline_count}')

    if current_total > baseline_total:
        regressions.insert(
            0,
            f'total mypy errors increased: {current_total}, baseline {baseline_total}',
        )

    if regressions:
        print('mypy baseline regression detected:')
        for item in regressions[:50]:
            print(f'  - {item}')
        if len(regressions) > 50:
            print(f'  ... and {len(regressions) - 50} more')
        print('\nRun this for full output:')
        print(
            '  docker compose exec -T backend uv run mypy app --explicit-package-bases --no-error-summary'
        )
        return 1

    if current_total < baseline_total:
        print(
            f'mypy passed baseline: {current_total} error(s), '
            f'improved from {baseline_total}. Update backend/mypy-baseline.json '
            'when intentionally paying down type debt.'
        )
    else:
        print(f'mypy passed baseline: {current_total} known error(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
