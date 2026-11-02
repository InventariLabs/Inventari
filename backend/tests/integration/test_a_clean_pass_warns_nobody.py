"""A clean reconciliation pass warns nobody, and a warning says what disagrees.

The scheduled job warned the admins whenever the figures changed, and it
never asked whether the new figures were a drift. The first pass of every
organization has nothing stored to compare with, so every new organization
was told "Stock drift detected" in its first minute — beside a screen that
said "In agreement" — and a drift that disappeared was announced the same
way as one that appeared. Only a drift is news now: it warns when it appears
or changes, reminds while it stands, and a clean pass is stored in silence.

The warning named the pairs the way the model does ("item/quant,
quant/ledger, layer/quant"), which a household reads as noise. It now names
only the pairs that disagree, in the words the reconciliation screen uses
for them.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import SUPPORTED_LANGUAGES
from app.models.notification import Notification
from app.services.reconciliation_job import (
    _record_pass_and_alert_admins_async,
    read_previous_measurement_async,
    reconcile_organization_async,
)

pytestmark = pytest.mark.asyncio

_CLEAN = {
    'quant_move_drift_count': 0,
    'quant_move_drift_total': Decimal('0.000'),
    'layer_quant_drift_count': 0,
    'layer_quant_drift_total': Decimal('0.000'),
}
_DRIFT = {
    **_CLEAN,
    'quant_move_drift_count': 2,
    'quant_move_drift_total': Decimal('5.000'),
    'layer_quant_drift_count': 1,
    'layer_quant_drift_total': Decimal('3.000'),
}


async def _warnings(db: AsyncSession, user_id) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at)
            )
        ).all()
    )


async def test_the_first_pass_of_a_new_organization_warns_nobody(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    figures = await reconcile_organization_async(db, async_test_household.id)
    assert figures == _CLEAN, 'a new organization has nothing to disagree about'

    await _record_pass_and_alert_admins_async(
        db, async_test_household.id, figures, datetime.now(UTC)
    )
    await db.commit()

    assert await _warnings(db, async_test_user.id) == []
    # Silent, not skipped: the screen still gets the pass to show as previous.
    assert await read_previous_measurement_async(db, async_test_household.id)


async def test_a_drift_that_disappears_warns_nobody(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    for figures in (_DRIFT, _CLEAN):
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

    seen = await _warnings(db, async_test_user.id)
    assert [row.title for row in seen] == ['Stock drift detected']


async def test_a_drift_that_comes_back_is_news_again(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    for figures in (_DRIFT, _CLEAN, _DRIFT):
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

    assert len(await _warnings(db, async_test_user.id)) == 2


async def test_the_warning_names_only_what_disagrees_in_the_screens_words(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    ledger_only = {
        **_DRIFT,
        'layer_quant_drift_count': 0,
        'layer_quant_drift_total': Decimal('0.000'),
    }
    await _record_pass_and_alert_admins_async(
        db, async_test_household.id, ledger_only, datetime.now(UTC)
    )
    await db.commit()

    (warning,) = await _warnings(db, async_test_user.id)
    assert 'the shelf vs the movement ledger: 2' in warning.content
    # The pair that agrees is not listed.
    assert 'the cost history' not in warning.content
    assert 'Statistics → Reconciliation' in warning.content


@pytest.mark.parametrize('standing', [False, True])
async def test_no_language_speaks_in_the_models_layers(standing: bool) -> None:
    from app.services.reconciliation_job import _drift_content

    content = _drift_content(_DRIFT, standing=standing)

    assert set(content) == {str(lang) for lang in SUPPORTED_LANGUAGES}
    for language, text in content.items():
        for layer_name in ('quant', 'layer', 'item/', '/ledger'):
            assert layer_name not in text, (language, text)
        for count in ('2', '1'):
            assert count in text, (language, text)
