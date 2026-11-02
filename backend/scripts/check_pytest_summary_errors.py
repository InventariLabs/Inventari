"""Fail when the pytest summary line carries errors, not only failures.

An ERROR at setup is not a failed test: the summary reads green to anyone
filtering for "failed", and the exit code dies in whatever pipe the run was
pushed through. The suite feeds this script the run's log; any summary line
counting a non-zero number of errors fails the check, so a run whose tests
did not execute cannot pass as if nothing happened.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Only the double-ruled summary lines (===== 12 passed, 2 errors =====) —
# test output and assertion messages may mention "1 error" in their own
# lines without meaning the run carried one.
_SUMMARY_WITH_ERRORS = re.compile(r'^=+ .*[1-9][0-9]* errors?\b', re.MULTILINE)


def summary_carries_errors(log: str) -> bool:
    return bool(_SUMMARY_WITH_ERRORS.search(log))


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: check_pytest_summary_errors.py <pytest-log-path>')
        return 2
    log = Path(sys.argv[1]).read_text(errors='replace')
    if summary_carries_errors(log):
        match = _SUMMARY_WITH_ERRORS.search(log)
        print(
            'the pytest summary carries errors — tests reported as errors '
            f'DID NOT RUN ({match.group(0).strip("=").strip() if match else ""}). '
            'Do not read the passed count as the whole story.'
        )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
