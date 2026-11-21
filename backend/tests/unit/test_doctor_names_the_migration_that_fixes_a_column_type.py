"""The doctor's column-type warning says whether a migration is about to fix it.

An upgrading owner reads the first lines of the log. A warning that only says
the list may survive a restart looks like a failure; one that names the
revision the start applies next reads as the expected step it is.
"""

from io import StringIO

import pytest
from rich.console import Console

from app.cli import commands_db
from app.core.migration_doctor import ColumnTypeDrift

DRIFT = [
    ColumnTypeDrift(
        table='ai_usage_logs',
        column='estimated_cost_usd',
        live_type='DOUBLE PRECISION',
        model_type='NUMERIC(14, 8)',
    )
]


@pytest.fixture
def printed(monkeypatch):
    buffer = StringIO()
    monkeypatch.setattr(
        commands_db, 'console', Console(file=buffer, width=400, highlight=False)
    )
    return buffer


def test_a_pending_revision_is_named_and_called_expected(printed):
    commands_db._print_column_type_drift(DRIFT, ['aicost01'])

    text = printed.getvalue()
    assert 'Not yet applied: aicost01' in text
    assert 'expected while upgrading' in text
    assert 'ai_usage_logs.estimated_cost_usd' in text


def test_without_a_pending_revision_the_old_warning_stays(printed):
    commands_db._print_column_type_drift(DRIFT)

    text = printed.getvalue()
    assert 'Not yet applied' not in text
    assert 'nothing will' in text


def test_no_drift_prints_nothing(printed):
    commands_db._print_column_type_drift([], ['aicost01'])

    assert printed.getvalue() == ''
