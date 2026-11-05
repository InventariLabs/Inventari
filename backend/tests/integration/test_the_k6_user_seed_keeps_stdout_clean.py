"""The k6 user seed writes only the CSV to stdout under --stdout.

`load_tests/prepare.sh` redirects stdout into users.csv. The seed's progress
line ("Created 10/N...") and its clean-up report went through a bare print, so
on a first run the file began with that text glued to the header and was not a
valid CSV for any generic reader.
"""

from __future__ import annotations

import sys

import pytest
from sqlalchemy.orm import Session

import seed_load_test_users as seed


def test_stdout_mode_prints_the_csv_and_nothing_else(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # SessionLocal is the script's own session; hand it the test session and
    # keep the script from closing it.
    monkeypatch.setattr(seed, 'SessionLocal', lambda: db_session)
    monkeypatch.setattr(db_session, 'close', lambda: None)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'seed_load_test_users.py',
            '--count',
            '12',
            '--prefix',
            'k6stdout',
            '--clean',
            '--stdout',
        ],
    )
    monkeypatch.setenv('K6_PASSWORD', 'k6-seed-test-pw')

    seed.main()

    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0] == 'email,password'
    assert len(lines) == 13
    assert 'Created' in err
