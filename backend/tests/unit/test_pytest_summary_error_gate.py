"""The summary gate refuses a run whose tests errored instead of ran."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

from check_pytest_summary_errors import summary_carries_errors


def test_a_summary_counting_errors_is_refused():
    log = (
        'tests/unit/test_example.py F\n'
        'ERROR app/tests/integration/test_async_smoke.py::test_real_async_client_create_storage\n'
        '===== 9248 passed, 5 skipped, 44 warnings, 77 errors in 125.32s =====\n'
    )
    assert summary_carries_errors(log), (
        'seventy-seven setup errors under a green passed count is exactly '
        'the shape this gate exists to catch'
    )


def test_a_single_error_in_the_summary_is_refused():
    log = '===== 1 passed, 1 error in 3.2s =====\n'
    assert summary_carries_errors(log)


def test_a_clean_summary_passes():
    log = '===== 9325 passed, 5 skipped, 44 warnings in 124.39s =====\n'
    assert not summary_carries_errors(log)


def test_an_error_mentioned_by_test_output_does_not_trip_the_gate():
    # A test's own output may say "1 error" mid-line; only the double-ruled
    # summary lines count, so the gate cannot be tripped by what a test
    # printed on its way through.
    log = (
        'E       AssertionError: expected 1 error, got none\n'
        'tests/unit/test_example.py F\n'
        '===== 9325 passed, 5 skipped in 124.39s =====\n'
    )
    assert not summary_carries_errors(log)


def test_a_zero_error_summary_passes():
    log = '===== 12 passed, 0 errors in 1.0s =====\n'
    assert not summary_carries_errors(log)
