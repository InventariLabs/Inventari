"""A backend start does not run the reconciliation for organizations measured lately.

The scheduler runs a job once as a process comes up and then on its interval,
and a backend starts several web workers. Without a look at the stored pass,
every start measured every organization again — a comparison that reads the
whole ledger — beside the users the same worker was serving.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reconciliation_job import (
    RECONCILIATION_INTERVAL,
    _is_due_async,
    _record_pass_and_alert_admins_async,
)

pytestmark = pytest.mark.asyncio

_CLEAN = {
    'quant_move_drift_count': 0,
    'quant_move_drift_total': Decimal('0.000'),
    'layer_quant_drift_count': 0,
    'layer_quant_drift_total': Decimal('0.000'),
}


async def test_an_organization_never_measured_is_due(
    real_async_db_session: AsyncSession, async_test_household
) -> None:
    assert await _is_due_async(
        real_async_db_session, async_test_household.id, datetime.now(UTC)
    )


async def test_an_organization_measured_a_moment_ago_is_not_due(
    real_async_db_session: AsyncSession, async_test_household
) -> None:
    db = real_async_db_session
    now = datetime.now(UTC)
    await _record_pass_and_alert_admins_async(
        db, async_test_household.id, _CLEAN, now - timedelta(minutes=1)
    )
    await db.commit()

    assert not await _is_due_async(db, async_test_household.id, now)


async def test_an_organization_measured_an_interval_ago_is_due_again(
    real_async_db_session: AsyncSession, async_test_household
) -> None:
    db = real_async_db_session
    now = datetime.now(UTC)
    await _record_pass_and_alert_admins_async(
        db, async_test_household.id, _CLEAN, now - RECONCILIATION_INTERVAL
    )
    await db.commit()

    assert await _is_due_async(db, async_test_household.id, now)
