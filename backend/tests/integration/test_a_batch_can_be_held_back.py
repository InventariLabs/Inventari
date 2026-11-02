"""A batch can be held back, and nobody could see it.

``StockLot.status`` has carried quarantine, hold, expiry and recall since the
warehouse modules were written, and every picking path obeys it.
Nothing displayed it and nothing could change it: an operator told that a
batch is bad had no way to say so, and an operator who had said so had no way
to take it back.

The batch that is held back also has to be able to leave. Scrapping is the
one thing you are supposed to do with a recalled batch, and it went through
the same guard as consumption — so the only way to dispose of it was to
release it first, which erased the recall. A disposal is not a consumption,
and now says so — on the draw a scrap document takes, where it is tested
(``test_a_scrap_still_takes_a_held_batch_the_line_names`` and
``test_a_held_batch_is_held_on_every_path`` in the warehouse module).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Batches:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.aisle: StorageLocation
        self.flour: ProductTemplate
        self.good: StockLot
        self.recalled: StockLot


@pytest.fixture
async def batches(real_async_db_session: AsyncSession) -> _Batches:
    db = real_async_db_session
    fixture = _Batches()

    fixture.org = Organization(
        name=f'Held Batches {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'quality_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    fixture.aisle = StorageLocation(
        name='Aisle 1',
        organization_id=fixture.org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.user.id,
    )
    db.add(fixture.aisle)
    await db.flush()

    fixture.flour = ProductTemplate(name='Rye flour', organization_id=fixture.org.id)
    db.add(fixture.flour)
    await db.flush()

    fixture.good = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-GOOD',
    )
    fixture.recalled = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-BAD',
    )
    db.add_all([fixture.good, fixture.recalled])
    await db.flush()

    await put_on_shelf(
        db, fixture.user, fixture.flour, fixture.aisle.id, 10, lot_id=fixture.good.id
    )
    await put_on_shelf(
        db, fixture.user, fixture.flour, fixture.aisle.id, 4, lot_id=fixture.recalled.id
    )
    # The bad batch arrived like any other; the recall came after.
    fixture.recalled.status = LotStatus.RECALLED
    await db.commit()
    return fixture


class TestTheBatchesAreListed:
    async def test_a_recalled_batch_is_on_the_list_and_says_so(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-lots', headers=_auth(batches.user)
        )

        assert response.status_code == status.HTTP_200_OK
        rows = {row['name']: row for row in response.json()['items']}
        assert rows['L-BAD']['status'] == LotStatus.RECALLED
        assert rows['L-GOOD']['status'] == LotStatus.ACTIVE

    async def test_a_row_names_its_product_and_what_is_left(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-lots', headers=_auth(batches.user)
        )

        rows = {row['name']: row for row in response.json()['items']}
        assert rows['L-BAD']['product_name'] == 'Rye flour'
        assert Decimal(rows['L-BAD']['on_hand']) == Decimal('4.000')

    async def test_the_list_can_be_narrowed_to_what_is_held_back(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-lots',
            params={'status': LotStatus.RECALLED},
            headers=_auth(batches.user),
        )

        # The question on a recall day is "what is held back", not "what
        # batches exist".
        assert response.json()['total'] == 1
        assert response.json()['items'][0]['name'] == 'L-BAD'


class TestTheStatusCanBeChanged:
    async def test_a_batch_can_be_held_back_with_a_reason(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.QUARANTINED, 'reason': 'Supplier notice 41/26'},
            headers=_auth(batches.user),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['status'] == LotStatus.QUARANTINED

    async def test_a_batch_can_be_let_go_again(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.recalled.id}',
            json={
                'status': LotStatus.ACTIVE,
                'reason': 'Supplier withdrew notice 41/26',
            },
            headers=_auth(batches.user),
        )

        assert response.json()['status'] == LotStatus.ACTIVE

    async def test_a_status_nobody_defined_is_refused(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': 'probably-fine'},
            headers=_auth(batches.user),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_another_organization_cannot_release_the_batch(
        self,
        real_async_client: AsyncClient,
        batches: _Batches,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        stranger_org = Organization(
            name=f'Stranger {uuid4().hex[:6]}', enabled_modules=['core', 'items']
        )
        db.add(stranger_org)
        await db.commit()
        stranger = await ModuleTestHelper.create_user_async(
            db, stranger_org, email=f'stranger_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()

        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.recalled.id}',
            json={'status': LotStatus.ACTIVE, 'reason': 'Not mine to release'},
            headers=_auth(stranger),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestNoStatusChangeWithoutAReason:
    """One rule, for holds and releases alike.

    A status without a reason answers a question asked six months later with
    "somebody clicked", which is the hole this screen was supposed to close.
    Releasing was argued as the exception — undoing your own slip should not
    cost a paragraph — and it lost: letting a recalled batch back onto the
    shelf is exactly the decision an auditor asks about, and a rule with one
    exception is two rules.

    The module paths are deliberately outside this: ``quarantine_lot_async``
    and ``release_lot_async`` are code acting on a rule, and there is nobody
    to ask. Which is why the requirement sits on the request schema and not
    in the service.
    """

    async def test_holding_a_batch_back_without_one_is_refused(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.QUARANTINED},
            headers=_auth(batches.user),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_letting_it_go_without_one_is_refused_too(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.recalled.id}',
            json={'status': LotStatus.ACTIVE},
            headers=_auth(batches.user),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_a_space_bar_is_not_a_reason(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.HELD, 'reason': '   '},
            headers=_auth(batches.user),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_the_status_did_not_move_when_the_reason_was_refused(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        """A refusal that had already changed the batch would be the worst
        of both: no explanation recorded and the stock held anyway."""
        await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.QUARANTINED},
            headers=_auth(batches.user),
        )

        after = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )
        assert after.json()['status'] == LotStatus.ACTIVE


class TestTheReasonIsReadableAfterwards:
    async def test_the_batch_reports_why_it_is_held(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.QUARANTINED, 'reason': 'Supplier notice 41/26'},
            headers=_auth(batches.user),
        )

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )

        # Beside the status, not buried in a blob the screen would have to
        # know the shape of.
        body = detail.json()
        assert body['status'] == LotStatus.QUARANTINED
        assert body['status_reason'] == 'Supplier notice 41/26'

    async def test_the_list_carries_it_too(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.HELD, 'reason': 'Waiting on the lab'},
            headers=_auth(batches.user),
        )

        listing = await real_async_client.get(
            '/api/v1/stock-lots', headers=_auth(batches.user)
        )

        rows = {row['id']: row for row in listing.json()['items']}
        assert rows[str(batches.good.id)]['status_reason'] == 'Waiting on the lab'

    async def test_the_entry_says_when_and_by_whom(
        self,
        real_async_client: AsyncClient,
        batches: _Batches,
        real_async_db_session: AsyncSession,
    ) -> None:
        """A reason with no date and no name only half answers the question."""
        await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.RECALLED, 'reason': 'Glass in jar 12'},
            headers=_auth(batches.user),
        )

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )

        entry = detail.json()['meta_data']['status_history'][-1]
        assert entry['reason'] == 'Glass in jar 12'
        assert entry['by'] == str(batches.user.id)
        assert entry['at'].startswith('20')

    async def test_a_reason_left_behind_by_an_older_status_is_not_shown(
        self,
        real_async_client: AsyncClient,
        batches: _Batches,
        real_async_db_session: AsyncSession,
    ) -> None:
        """The module paths change the status without writing an entry.

        So the newest entry can describe a state the batch has since left,
        and showing it beside the current status would explain the wrong
        decision. Silence is the honest answer.
        """
        from app.services._stock_lot_ops import release_lot_async

        lot_id, org_id, auth = batches.good.id, batches.org.id, _auth(batches.user)
        await real_async_client.patch(
            f'/api/v1/stock-lots/{lot_id}',
            json={'status': LotStatus.QUARANTINED, 'reason': 'Supplier notice 41/26'},
            headers=auth,
        )

        # The API changed the row through its own session; this one still
        # holds the copy the fixture made, and would write 'active' over
        # 'active' and change nothing.
        real_async_db_session.expire_all()
        await release_lot_async(real_async_db_session, org_id, lot_id)
        await real_async_db_session.commit()

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{lot_id}', headers=auth
        )

        body = detail.json()
        assert body['status'] == LotStatus.ACTIVE
        assert body['status_reason'] is None


class TestEveryReasonIsKept:
    """The first reason is not the only reason.

    A batch is held on a supplier's word, released on the lab's, recalled on
    the next notice. Only the first of those ever reached the database: the
    service copied ``meta_data`` shallowly and appended to the very list the
    ORM had loaded, so the new value compared equal to the old one and no
    UPDATE was sent. The first write survived only because it started from
    NULL.
    """

    async def _set_status(
        self,
        client: AsyncClient,
        batches: _Batches,
        lot_status: str,
        reason: str,
    ) -> None:
        response = await client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': lot_status, 'reason': reason},
            headers=_auth(batches.user),
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    async def test_a_second_change_writes_a_second_entry(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await self._set_status(
            real_async_client, batches, LotStatus.HELD, 'Supplier notice 41/26'
        )
        await self._set_status(
            real_async_client, batches, LotStatus.ACTIVE, 'Lab cleared it'
        )

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )

        history = detail.json()['meta_data']['status_history']
        assert [entry['reason'] for entry in history] == [
            'Supplier notice 41/26',
            'Lab cleared it',
        ]

    async def test_the_current_reason_is_the_current_one(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await self._set_status(
            real_async_client, batches, LotStatus.HELD, 'Supplier notice 41/26'
        )
        await self._set_status(
            real_async_client, batches, LotStatus.RECALLED, 'Glass in jar 12'
        )

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )

        # Without the second entry this read `None`: the guard that hides a
        # stale explanation was doing its job on data that never arrived.
        assert detail.json()['status_reason'] == 'Glass in jar 12'

    async def test_quarantining_twice_keeps_the_newer_reason(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await self._set_status(
            real_async_client, batches, LotStatus.QUARANTINED, 'First suspicion'
        )
        await self._set_status(
            real_async_client, batches, LotStatus.QUARANTINED, 'Second, worse one'
        )

        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batches.good.id}', headers=_auth(batches.user)
        )

        assert detail.json()['status_reason'] == 'Second, worse one'


class TestTheOrganizationJournalHearsAboutIt:
    """Whether a batch is fit to use is a custody act, and the journal says
    custody acts belong in it. This one was not reaching it at all, so the
    question "why did this batch ship after the supplier called" had no
    answer anywhere: the card said Active, the journal said nothing, and the
    reason the operator had to type was discarded.
    """

    async def test_holding_a_batch_back_is_written_to_the_journal(
        self, real_async_client: AsyncClient, batches: _Batches
    ) -> None:
        await real_async_client.patch(
            f'/api/v1/stock-lots/{batches.good.id}',
            json={'status': LotStatus.HELD, 'reason': 'Supplier notice 41/26'},
            headers=_auth(batches.user),
        )

        journal = await real_async_client.get(
            '/api/v1/audit-log', headers=_auth(batches.user)
        )

        assert journal.status_code == status.HTTP_200_OK
        entries = [
            entry
            for entry in journal.json()['items']
            if entry['target_type'] == 'stock_lot'
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['target_id'] == str(batches.good.id)
        assert entry['user_id'] == str(batches.user.id)
        assert entry['reason'] == 'Supplier notice 41/26'
        # Where it came from and where it went — a row that reads without
        # opening the batch.
        assert entry['snapshot']['previous_status'] == LotStatus.ACTIVE
        assert entry['snapshot']['status'] == LotStatus.HELD
        assert entry['snapshot']['lot_name'] == batches.good.name


class TestTheModuleDoorsAreJournalledToo:
    """A module holds a batch back through ``core_api.stock`` rather than the
    route — a quality hold raised on a receipt, released when the lab says so.
    The batch changes fitness all the same, so the journal hears it the same
    way, with the module's reason and the person the module acted for.
    """

    @staticmethod
    async def _lot_entries(db: AsyncSession, lot_id) -> list[AuditLog]:
        rows = await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.target_type == AuditTargetType.STOCK_LOT,
                AuditLog.target_id == lot_id,
            )
            .order_by(AuditLog.created_at.asc(), AuditLog.id)
        )
        return list(rows.all())

    async def test_a_hold_and_its_release_are_two_entries(
        self, real_async_db_session: AsyncSession, batches: _Batches
    ) -> None:
        db = real_async_db_session
        await core_api.stock.quarantine_lot_async(
            db,
            batches.org.id,
            batches.good.id,
            reason='Lab sample pending',
            user_id=batches.user.id,
        )
        await core_api.stock.release_lot_async(
            db, batches.org.id, batches.good.id, user_id=batches.user.id
        )

        held, released = await self._lot_entries(db, batches.good.id)
        assert held.action == released.action == AuditAction.UPDATE
        assert held.user_id == released.user_id == batches.user.id
        assert held.reason == 'Lab sample pending'
        assert held.snapshot == {
            'lot_name': 'L-GOOD',
            'previous_status': LotStatus.ACTIVE,
            'status': LotStatus.QUARANTINED,
        }
        assert released.reason is None
        assert released.snapshot == {
            'lot_name': 'L-GOOD',
            'previous_status': LotStatus.QUARANTINED,
            'status': LotStatus.ACTIVE,
        }

    async def test_releasing_a_batch_that_is_not_held_writes_nothing(
        self, real_async_db_session: AsyncSession, batches: _Batches
    ) -> None:
        db = real_async_db_session
        await core_api.stock.release_lot_async(db, batches.org.id, batches.good.id)

        assert await self._lot_entries(db, batches.good.id) == []
