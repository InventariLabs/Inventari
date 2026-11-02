from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / 'scripts' / 'vulture-baseline.txt'
VULTURE_COMMAND = [sys.executable, '-m', 'vulture']

# Findings are keyed by "path: message" (line number stripped) so that
# editing a file above a finding does not re-flag it as NEW (line-shift
# churn). Duplicate messages on the same path collapse into one key — the
# trade-off is acceptable for a dead-code gate.
FINDING_RE = re.compile(r'^(.+?\.py):\d+: (.*)$')


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    return {
        line.strip() for line in BASELINE_PATH.read_text().splitlines() if line.strip()
    }


def _collect_findings(output: str) -> set[str]:
    findings: set[str] = set()
    for line in output.splitlines():
        m = FINDING_RE.match(line.strip())
        if m:
            findings.add(f'{m.group(1)}: {m.group(2)}')
    return findings


def _run_vulture() -> tuple[int, set[str]]:
    result = subprocess.run(
        VULTURE_COMMAND,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    # vulture exit codes (2.16+): 0 = clean, 3 = dead code found.
    if result.returncode not in (0, 3):
        # Real vulture failure (bad config, crash) — surface it, do not
        # silently treat it as "clean".
        print(result.stdout, end='')
        return result.returncode, set()
    return 0, _collect_findings(result.stdout)


def _write_baseline(findings: set[str]) -> None:
    BASELINE_PATH.write_text(''.join(f'{f}\n' for f in sorted(findings)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Vulture dead-code check with baseline (fail only on new findings).'
    )
    parser.add_argument(
        '--write-baseline',
        action='store_true',
        help='Snapshot current vulture findings as the baseline and exit 0.',
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Print the full dead-code report without failing the build.',
    )
    args = parser.parse_args()

    rc, current = _run_vulture()
    if rc != 0:
        return rc

    if args.write_baseline:
        _write_baseline(current)
        print(
            f'vulture baseline written: {len(current)} finding(s) → {BASELINE_PATH.name}'
        )
        return 0

    if args.full:
        print(f'vulture: {len(current)} finding(s) (full report, non-blocking):')
        for finding in sorted(current):
            print(f'  - {finding}')
        print(
            '\nBaseline file: scripts/vulture-baseline.txt — run '
            'scripts/check_vulture_baseline.py --write-baseline to refresh.'
        )
        return 0

    baseline = _load_baseline()
    new_findings = current - baseline
    fixed = baseline - current

    if new_findings:
        print('vulture baseline regression — NEW dead-code finding(s):')
        for finding in sorted(new_findings):
            print(f'  - {finding}')
        print(
            '\nRemove the dead code. If the finding is a false positive, add an '
            'ignore (pyproject.toml [tool.vulture]) — do NOT grandfather it.'
        )
        return 1

    if fixed:
        print(
            f'vulture passed baseline: {len(current)} finding(s), '
            f'{len(fixed)} fixed/removed since baseline. '
            f'Run --write-baseline to refresh scripts/vulture-baseline.txt.'
        )
    else:
        print(f'vulture passed baseline: {len(current)} known finding(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
