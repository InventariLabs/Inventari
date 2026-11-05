"""The constraints that say stock cannot go negative are actually in force.

They were added ``NOT VALID`` — the right call at the time, since that skips
the table scan and the lock that comes with it — with a note to validate them
separately. Nobody did. An unvalidated constraint checks new writes and says
nothing about the rows already there, so the guarantee the migration was
written for was never obtained; and the planner will not use it either.

A violation had nowhere to land, besides. The database raises, nothing
recognises it, and the caller gets a bare 500 — the least informative
possible answer to "this would leave the shelf holding less than nothing".

What this file can and cannot say: the test schema is built from the models,
where these constraints are declared and therefore created valid, so it can
only hold the *declarations* in place — nobody drops one from a model
unnoticed. Whether the constraints on a database built by migration are
validated is a question about that database, answered by the migration
beside this test and checked against a running one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Every CHECK that stands between the stock tables and an impossible state.
#: The quant table's three went with the table; the promise it kept per row —
#: never more held than stocked — is kept per grain at commit by a trigger
#: (archived ``holdguard01``), tested in ``test_the_database_refuses_a_hold_past_its_grain.py``.
GUARDS = (
    'ck_items_quantity_nonneg',
    'ck_svl_remaining_not_negative',
)


class TestEveryStockGuardIsDeclared:
    async def test_every_guard_exists_and_is_in_force(
        self, real_async_db_session: AsyncSession
    ) -> None:
        rows = await real_async_db_session.execute(
            text(
                'SELECT conname, convalidated FROM pg_constraint '
                'WHERE conname = ANY(:names)'
            ),
            {'names': list(GUARDS)},
        )
        state = dict(rows.all())
        assert set(state) == set(GUARDS), f'missing: {set(GUARDS) - set(state)}'
        unvalidated = sorted(name for name, valid in state.items() if not valid)
        assert unvalidated == [], unvalidated
