"""A step of the scale seed's log counts the rows written to the table it names.

The locations step stages its shelves in a temporary table and then inserts
every location, the shelves among them: the log of that step must give the
rows of the insert, not the insert and the staging together.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import seed_scale_data as seed

pytestmark = pytest.mark.unit


class _Conn:
    """A connection whose statements report the row count written in their text."""

    def execute(self, statement, params=None):
        sql = str(statement)
        return SimpleNamespace(rowcount=int(sql.rsplit('--', 1)[1]))


def test_the_staging_rows_of_a_step_are_not_counted_again() -> None:
    steps = seed._Steps(_Conn())

    rows = steps.run(
        'locations',
        'CREATE TEMP TABLE scale_shelves AS SELECT 1 --880',
        'CREATE UNIQUE INDEX ON scale_shelves (idx) --0',
        'INSERT INTO storage_locations SELECT 1 --1012',
    )

    assert rows == 1012


def test_a_step_that_fills_several_tables_logs_each_table_apart(capsys) -> None:
    steps = seed._Steps(_Conn())

    rows = steps.run(
        'documents',
        'CREATE TEMP TABLE scale_docs AS SELECT 1 --1500',
        'INSERT INTO documents SELECT 1 --1281',
        'INSERT INTO purchase_orders SELECT 1 --122',
        'INSERT INTO purchase_order_lines SELECT 1 --695',
        'INSERT INTO documents SELECT 1 --3',
    )

    log = capsys.readouterr().out
    assert rows == 1281 + 122 + 695 + 3
    assert 'documents' in log and '1,284 rows' in log
    assert '122 rows' in log and '695 rows' in log
    assert '2,101' not in log


def test_a_step_that_only_stages_counts_what_it_staged() -> None:
    steps = seed._Steps(_Conn())

    assert (
        steps.run(
            'records (staging)',
            'CREATE TEMP TABLE a AS SELECT 1 --5',
            'CREATE TEMP TABLE b AS SELECT 1 --7',
        )
        == 12
    )


def test_the_default_building_has_about_a_thousand_locations() -> None:
    size = seed._sizes(100_000)

    # Zones, racks and shelves of the warehouse, its receiving zone and ten dock lanes.
    locations = (
        1 + size['zones'] + size['zones'] * size['racks'] + size['shelves'] + 1 + 10
    )
    assert size['shelves'] == 880
    assert 1_000 <= locations <= 1_030
