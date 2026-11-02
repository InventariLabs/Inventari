"""The reconciliation measures both pairs, and a scheduled job alerts on change.

The report used to compare one pair — ``Item.quantity`` against the quant
table — while two other disagreements were left to be presumed rather than
measured: the shelf-vs-ledger gap the hydration design left, and the shelf
the cost layers do not cover. The first pair ended with the table (there is
one number of stock now), and its fields went with it; these tests hold the
measured numbers of the other two, that the table's pairs stay gone, and the
job's alert-once-per-signature behaviour.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PreviousMeasurementDTO, ReconciliationDTO
from app.models.notification import Notification
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.schemas.item import ItemCreate
from app.services.items import create_item
from app.services.reconciliation_job import (
    _record_pass_and_alert_admins_async,
    read_previous_measurement_async,
    reconcile_organization_async,
)
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import shelf_keeper


async def _location(db: AsyncSession, org_id, user_id) -> StorageLocation:
    from app.models.storage_type import StorageType

    st = StorageType(name='Rec Shelf', type_code='REC_SHELF', behavior_mode='NONE')
    db.add(st)
    await db.flush()
    location = StorageLocation(
        name='Rec Location',
        organization_id=org_id,
        storage_type_id=st.id,
        created_by=user_id,
    )
    db.add(location)
    await db.flush()
    return location


async def _shelf(
    db: AsyncSession,
    org_id,
    location_id,
    *,
    name: str,
    shelf_qty: Decimal,
    layer_qty: Decimal | None,
) -> ProductTemplate:
    """A template with stock on the shelf and — optionally — a cost layer behind it.

    The stock is a record typed with the bridge off: no movement and no
    layer behind it, the shape a shelf stocked before its ledger has
    (ADR-004). The shelf the ledger and cost pairs measure is the records'
    own, so the record is what they see; the layer, when named, is the cost
    history the third pair holds it against.
    """
    template = ProductTemplate(name=name, organization_id=org_id)
    db.add(template)
    await db.flush()
    record = await create_item(
        db,
        ItemCreate(name=name, location_id=location_id, quantity=shelf_qty),
        await shelf_keeper(db, org_id),
        post_the_change=False,
    )
    assert record.template_id == template.id
    if layer_qty is not None:
        db.add(
            StockValuationLayer(
                organization_id=org_id,
                product_template_id=template.id,
                quantity=layer_qty,
                remaining_qty=layer_qty,
                unit_cost=Decimal('1.00'),
                total_value=layer_qty,
                direction='IN',
                currency='PLN',
            )
        )
    await db.commit()
    return template


@pytest.mark.asyncio
class TestThreePairsAreMeasured:
    async def test_the_hydration_gap_is_a_number_not_an_assumption(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """A shelf with no movements behind it: the ledger pair reports it.

        This is the shape every hydrated shelf has (ADR-004) — the old
        report could not see it, and the drift it guarantees was presumed
        rather than measured.
        """
        db = real_async_db_session
        location = await _location(db, async_test_household.id, async_test_user.id)
        await _shelf(
            db,
            async_test_household.id,
            location.id,
            name='Hydrated',
            shelf_qty=Decimal('7'),
            layer_qty=Decimal('7'),
        )

        result = await reconcile_organization_async(db, async_test_household.id)

        # Seven units on the shelf, zero units in the ledger: the whole
        # shelf is the hydration gap, and the report says so.
        assert result['quant_move_drift_count'] == 1
        assert result['quant_move_drift_total'] == 7.0
        # The layer pair ties — the cost history covers the shelf.
        assert result['layer_quant_drift_count'] == 0

    async def test_unpriced_arrivals_show_as_layer_gap(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        location = await _location(db, async_test_household.id, async_test_user.id)
        # On the shelf, priced by no layer: the unpriced-stock hole, measured.
        await _shelf(
            db,
            async_test_household.id,
            location.id,
            name='Unpriced',
            shelf_qty=Decimal('4'),
            layer_qty=None,
        )

        result = await reconcile_organization_async(db, async_test_household.id)

        assert result['layer_quant_drift_count'] == 1
        assert result['layer_quant_drift_total'] == 4.0


@pytest.mark.asyncio
class TestTheWireCarriesEveryPairThatWasMeasured:
    """Measuring three pairs and sending one is the same as measuring one.

    The read-model has reported three pairs since the ledger and the layers
    joined it, and ``response_model`` narrowed the HTTP answer back to the
    first — so the warning admins receive named three counts and the screen
    behind it could show none of them. Nothing in the frontend mentioned the
    new fields, because nothing could.
    """

    async def test_every_field_the_model_measures_reaches_the_reader(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        location = await _location(db, async_test_household.id, async_test_user.id)
        await _shelf(
            db,
            async_test_household.id,
            location.id,
            name='On the wire',
            shelf_qty=Decimal('7'),
            layer_qty=Decimal('4'),
        )

        response = await real_async_client.get(
            '/api/v1/stats/reconciliation',
            headers={
                'Authorization': 'Bearer '
                + create_access_token(data={'sub': str(async_test_user.id)})
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # The shelf holds seven with no movement behind it, and its cost
        # history covers four of them — one disagreement in each of the two
        # pairs the answer used to drop on the way out.
        assert body['quant_move_drift_count'] == 1
        assert body['quant_move_drift_total'] == '7.000'
        assert body['layer_quant_drift_count'] == 1
        assert body['layer_quant_drift_total'] == '3.000'
        # And how much was read to say it: nought over nothing is not the
        # same statement as nought over a warehouse.
        assert 'items_scanned' in body

    async def test_a_quantity_crosses_as_a_string(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """Decision 18: a stock quantity is exact, so it is not a JSON number.

        These figures were floats — the one type that cannot say whether
        a value was exact or rounded for transport, on a report whose whole
        job is to compare two exact records.
        """
        db = real_async_db_session
        location = await _location(db, async_test_household.id, async_test_user.id)
        await _shelf(
            db,
            async_test_household.id,
            location.id,
            name='Typed',
            shelf_qty=Decimal('3'),
            layer_qty=None,
        )

        response = await real_async_client.get(
            '/api/v1/stats/reconciliation',
            headers={
                'Authorization': 'Bearer '
                + create_access_token(data={'sub': str(async_test_user.id)})
            },
        )
        body = response.json()

        assert isinstance(body['quant_move_drift_total'], str)
        assert isinstance(body['layer_quant_drift_total'], str)


#: Every field the answer carries: the records it read, and the two pairs.
_THE_ANSWER = {
    'items_scanned',
    'quant_move_drift_count',
    'quant_move_drift_total',
    'layer_quant_drift_count',
    'layer_quant_drift_total',
    'previous',
}

#: What a previous pass says: when, and the two pairs' figures.
_THE_PREVIOUS_PASS = {
    'measured_at',
    'quant_move_drift_count',
    'quant_move_drift_total',
    'layer_quant_drift_count',
    'layer_quant_drift_total',
}


@pytest.mark.asyncio
class TestTheTablesPairsStayGone:
    """The two pairs that compared the records and their view with the quant
    table ended with it, and so did their fields: a flag that could only say
    "no drift", counts that could only say nought, a per-location breakdown
    that could only be empty. A field that comes back answers a question
    nothing measures — so the answer is held to exactly what is measured.
    """

    async def test_the_answer_is_the_two_pairs_and_what_they_read(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        headers = {
            'Authorization': 'Bearer '
            + create_access_token(data={'sub': str(async_test_user.id)})
        }
        figures = await reconcile_organization_async(db, async_test_household.id)
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/stats/reconciliation', headers=headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == _THE_ANSWER
        assert set(body['previous']) == _THE_PREVIOUS_PASS
        # The pass the job stores is made of the same figures.
        assert set(figures) == _THE_PREVIOUS_PASS - {'measured_at'}

    async def test_the_contract_carries_no_field_of_the_table(self) -> None:
        assert set(ReconciliationDTO.model_fields) == _THE_ANSWER - {'previous'}
        assert set(PreviousMeasurementDTO.model_fields) == _THE_PREVIOUS_PASS


@pytest.mark.asyncio
class TestTheJobAlertsOncePerSignature:
    async def test_drift_warns_admins_once_and_again_only_when_it_grows(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        figures = {
            'quant_move_drift_count': 1,
            'quant_move_drift_total': 7.0,
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': 0.0,
        }

        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()
        first = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert len(first) == 1
        # And it sends the reader somewhere. The link said '/stats', which is
        # not a route in this application, so a warning about drift ended on
        # Page Not Found.
        assert first[0].link == '/inventory/stats/reconciliation'

        # The same drift again: silence — a standing fact, not news.
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()
        second = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert len(second) == 1

        # The gap grows: the admins hear about it.
        figures['quant_move_drift_total'] = 9.0
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()
        third = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert len(third) == 2


@pytest.mark.asyncio
class TestAStandingDriftComesBackWeekly:
    """A drift that stands unchanged used to warn once and never again.

    "A fact of the hydration design" was the reason, and a fact the admins
    are told about once is one nobody looks at after that week. Unchanged
    non-zero figures now come back once seven days after the admins last
    heard of them, with a sentence that says the drift is still there.
    """

    async def _count(self, db, user_id) -> list[Notification]:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(Notification.user_id == user_id)
                    .order_by(Notification.created_at)
                )
            ).all()
        )

    async def test_an_unchanged_drift_is_repeated_once_a_week_and_not_more(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        figures = {
            'quant_move_drift_count': 2,
            'quant_move_drift_total': Decimal('5.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        start = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)

        for days, expected in ((0, 1), (6, 1), (7, 2), (8, 2), (13, 2), (14, 3)):
            await _record_pass_and_alert_admins_async(
                db, async_test_household.id, figures, start + timedelta(days=days)
            )
            await db.commit()
            seen = await self._count(db, async_test_user.id)
            assert len(seen) == expected, f'day {days}'

        # The reminder says the drift is still there, not that it was found.
        assert seen[0].title == 'Stock drift detected'
        assert seen[1].title == 'Stock drift still standing'
        assert 'the shelf vs the movement ledger: 2' in seen[1].content
        assert seen[1].link == '/inventory/stats/reconciliation'

    async def test_clean_figures_stay_silent_however_long_they_stand(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        clean = {
            'quant_move_drift_count': 0,
            'quant_move_drift_total': Decimal('0.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        start = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        for days in (0, 7, 14, 30):
            await _record_pass_and_alert_admins_async(
                db, async_test_household.id, clean, start + timedelta(days=days)
            )
            await db.commit()

        # Nothing stands, so nothing is said — not on the first pass either.
        assert await self._count(db, async_test_user.id) == []


class TestTheWarningIsWrittenInTheReadersLanguage:
    async def test_each_admin_reads_it_in_their_own_language(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """A notification row is text, so the language is chosen when written.

        The warning was one English literal for every admin at once: a Polish
        administrator read "Stock drift detected" beside notifications that
        were already translated, and it sent them to "Stats → Reconciliation"
        — labels no screen carries in either language.
        """
        db = real_async_db_session
        async_test_user.preferred_language = 'pl'
        colleague = User(
            email=f'drift_{uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name='Drift Reader',
            organization_id=async_test_household.id,
            role='admin',
            is_active=True,
            preferred_language='en',
        )
        db.add(colleague)
        await db.commit()
        await db.refresh(colleague)

        figures = {
            'quant_move_drift_count': 142,
            'quant_move_drift_total': 142.0,
            'layer_quant_drift_count': 78,
            'layer_quant_drift_total': 78.0,
        }
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

        async def _only(user_id) -> Notification:
            rows = (
                await db.scalars(
                    select(Notification).where(Notification.user_id == user_id)
                )
            ).all()
            assert len(rows) == 1
            return rows[0]

        polish = await _only(async_test_user.id)
        english = await _only(colleague.id)

        assert polish.title == 'Wykryto rozjazd stanów'
        # The reference names the tabs the way this reader's interface does.
        assert 'Statystyki → Uzgodnienie' in polish.content
        assert '142' in polish.content
        assert english.title == 'Stock drift detected'
        assert 'Statistics → Reconciliation' in english.content
        # Neither reader gets the other's sentence.
        assert 'Statystyki' not in english.content
        assert 'Stock drift' not in polish.content


@pytest.mark.asyncio
class TestTheScreenReadsTheRecordTheWarningReads:
    """One stored pass answers both readers.

    The screen's "previous" and the warning's "changed?" question used to
    have only a bare signature string between them — a record no screen
    could show. The job now stores every pass with its timestamp, and the
    endpoint hands it out beside the fresh figures.
    """

    async def test_every_pass_is_stored_and_a_standing_drift_stays_silent(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        figures = {
            'quant_move_drift_count': 1,
            'quant_move_drift_total': Decimal('7.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        first_pass = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
        second_pass = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, first_pass
        )
        await db.commit()
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, second_pass
        )
        await db.commit()

        # The standing drift warned once — the second pass compared figures,
        # not timestamps, and stayed silent.
        notifications = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert len(notifications) == 1

        # But the record moved: the screen's "previous" is the pass before
        # this one, not the day the drift last changed.
        previous = await read_previous_measurement_async(db, async_test_household.id)
        assert previous is not None
        assert previous.measured_at == second_pass
        assert previous.quant_move_drift_count == 1
        assert previous.quant_move_drift_total == Decimal('7.000')

    async def test_the_wire_carries_the_previous_pass(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        location = await _location(db, async_test_household.id, async_test_user.id)
        await _shelf(
            db,
            async_test_household.id,
            location.id,
            name='On the wire',
            shelf_qty=Decimal('7'),
            layer_qty=Decimal('4'),
        )
        headers = {
            'Authorization': 'Bearer '
            + create_access_token(data={'sub': str(async_test_user.id)})
        }

        # Before the job's first pass there is nothing to compare against,
        # and the answer says so instead of inventing a zero.
        before = await real_async_client.get(
            '/api/v1/stats/reconciliation', headers=headers
        )
        assert before.status_code == 200, before.text
        assert before.json()['previous'] is None

        figures = await reconcile_organization_async(db, async_test_household.id)
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

        after = await real_async_client.get(
            '/api/v1/stats/reconciliation', headers=headers
        )
        assert after.status_code == 200, after.text
        previous = after.json()['previous']
        assert previous is not None
        assert previous['quant_move_drift_count'] == 1
        assert previous['quant_move_drift_total'] == '7.000'
        assert previous['layer_quant_drift_count'] == 1
        assert previous['layer_quant_drift_total'] == '3.000'
        assert previous['measured_at'] is not None

    async def test_a_pass_stored_while_there_was_a_table_still_compares(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """A pass stored before the table went carries its two pairs too.

        Their figures are not measured any more, so they are left out of
        what is compared: a drift standing on the pairs that remain stays
        silent on the first pass after the table went, instead of being
        announced as if it had just been found.
        """
        db = real_async_db_session
        from app.core.public_api import core_api

        figures = {
            'quant_move_drift_count': 1,
            'quant_move_drift_total': Decimal('7.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        stored_then = {
            'item_quant_drift_count': '0',
            'item_quant_drift_total': '0.000',
            **{key: str(value) for key, value in figures.items()},
        }
        await core_api.settings.set_bulk_async(
            db,
            async_test_household.id,
            'core',
            {
                'reconciliation_drift_signature': json.dumps(
                    {
                        'measured_at': '2026-09-20T06:00:00+00:00',
                        'alerted_at': '2026-09-20T06:00:00+00:00',
                        'figures': stored_then,
                    }
                )
            },
        )
        await db.commit()

        previous = await read_previous_measurement_async(db, async_test_household.id)
        assert previous is not None
        assert previous.quant_move_drift_total == Decimal('7.000')

        await _record_pass_and_alert_admins_async(
            db,
            async_test_household.id,
            figures,
            datetime(2026, 9, 21, 6, 0, tzinfo=UTC),
        )
        await db.commit()

        notifications = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert notifications == []

    async def test_a_record_from_the_bare_signature_days_still_compares(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """Records written before the pass carried its timestamp keep working.

        The stored value was the bare signature string; a standing drift
        against such a record must stay silent, and the pass that reads it
        rewrites it in the structured shape the screen can show.
        """
        db = real_async_db_session
        from app.core.public_api import core_api

        figures = {
            'quant_move_drift_count': 1,
            'quant_move_drift_total': Decimal('7.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        bare_signature = '|'.join(str(figures[key]) for key in sorted(figures))
        await core_api.settings.set_bulk_async(
            db,
            async_test_household.id,
            'core',
            {'reconciliation_drift_signature': bare_signature},
        )
        await db.commit()

        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

        # Same figures as the bare record: silence, not a second warning.
        notifications = (
            await db.scalars(
                select(Notification).where(Notification.user_id == async_test_user.id)
            )
        ).all()
        assert len(notifications) == 0

        # And the record the screen reads has the shape with a timestamp.
        previous = await read_previous_measurement_async(db, async_test_household.id)
        assert previous is not None
        assert previous.quant_move_drift_total == Decimal('7.000')
        assert previous.measured_at is not None

    async def test_a_record_of_another_shape_reads_as_never_measured(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
    ) -> None:
        """A value under the key that is not the stored pass fails nothing.

        Only a hand-made write puts one there, and the readers called
        ``startswith`` on it: the screen answered with an error and the pass
        failed before it could write its own record over it.
        """
        db = real_async_db_session
        from app.core.public_api import core_api

        await core_api.settings.set_bulk_async(
            db,
            async_test_household.id,
            'core',
            {'reconciliation_drift_signature': {'measured_at': 'yesterday'}},
        )
        await db.commit()

        assert (
            await read_previous_measurement_async(db, async_test_household.id)
        ) is None

        figures = {
            'quant_move_drift_count': 0,
            'quant_move_drift_total': Decimal('0.000'),
            'layer_quant_drift_count': 0,
            'layer_quant_drift_total': Decimal('0.000'),
        }
        await _record_pass_and_alert_admins_async(
            db, async_test_household.id, figures, datetime.now(UTC)
        )
        await db.commit()

        previous = await read_previous_measurement_async(db, async_test_household.id)
        assert previous is not None
        assert previous.quant_move_drift_count == 0
