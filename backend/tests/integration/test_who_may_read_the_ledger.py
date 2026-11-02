"""Which of the four levels may open the ledger, and what each of them sees.

Every screen the movement ledger brought with it — the movements, the
shelves, the batches, the stock on a given day — is guarded by
``items:read``, and the one thing any of them can change (a batch's status)
by ``items:write``. That is one line per endpoint and nothing tested it, so
the answer to "can the warehouseman see this" was a matter of reading the
router rather than of running anything.

The answer, written down here so it is a decision rather than an accident:

* **admin** — everything, by the bypass in ``UserContextDTO.has_permission``.
* **manager** and **user** — identical. Both resolve to ``_MEMBER``, which
  carries both halves, so an ordinary member sees exactly what a manager
  sees and may hold a batch back just the same. There is no rank between
  them on any of these screens.
* **viewer** — reads all four, and is refused the batch status. This is the
  only line in the matrix where the levels part company.

And what is on the screens is worth stating too, because the question these
tests were written for was "does a warehouseman see the costs". On the
ledger itself: there are none. ``StockMoveRowDTO`` carries quantity, places,
batch and author, and no money at all; so does the shelves list. The one
screen that carries value is the report of stock on a given day, and it is
open to every level including a viewer. Pinned below so that changing it is
a decision somebody makes on purpose.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

#: Every ``User.role`` a real account can hold, most authority first.
_LEVELS = ('admin', 'manager', 'user', 'viewer')


class _Ledger:
    def __init__(self) -> None:
        self.users: dict[str, User]
        self.lot_id: str


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def ledger(real_async_db_session: AsyncSession) -> _Ledger:
    """One warehouse with something in it, and one account per level."""
    db = real_async_db_session
    fixture = _Ledger()

    org = Organization(
        name=f'Roles {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    fixture.users = {
        level: await ModuleTestHelper.create_user_async(
            db, org, email=f'{level}_{uuid4().hex[:8]}@test.com', role=level
        )
        for level in _LEVELS
    }
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.users['admin'].id,
    )
    product = ProductTemplate(name='Rye flour', organization_id=org.id)
    db.add_all([location, product])
    await db.flush()

    lot = StockLot(
        organization_id=org.id,
        product_template_id=product.id,
        name='L-2026-04',
    )
    db.add(lot)
    await db.flush()
    fixture.lot_id = str(lot.id)

    await put_on_shelf(
        db, fixture.users['admin'], product, location.id, 20, lot_id=lot.id
    )
    # The twenty arrived on the day the ledger reads are asked about.
    arrival = await db.scalar(
        select(StockMove).where(StockMove.product_template_id == product.id)
    )
    arrival.completed_at = _NOW
    await db.commit()
    return fixture


#: Every way into the ledger. All four are reads and all four are guarded by
#: the same permission, which is the point: they are one screen's worth of
#: question asked four ways.
_READS = (
    ('/api/v1/stock-moves', {}),
    ('/api/v1/stock-quants', {}),
    ('/api/v1/stock-lots', {}),
    ('/api/v1/stock-as-of', {'as_of': _NOW.isoformat()}),
)


class TestEveryLevelMayReadTheLedger:
    @pytest.mark.parametrize('level', _LEVELS)
    @pytest.mark.parametrize(('path', 'params'), _READS)
    async def test_the_four_reads_are_open_to_all_four_levels(
        self,
        real_async_client: AsyncClient,
        ledger: _Ledger,
        level: str,
        path: str,
        params: dict[str, str],
    ) -> None:
        response = await real_async_client.get(
            path, params=params, headers=_auth(ledger.users[level])
        )

        assert response.status_code == 200, (level, path, response.text)

    @pytest.mark.parametrize('level', _LEVELS)
    async def test_the_sheet_comes_out_for_all_four_levels(
        self, real_async_client: AsyncClient, ledger: _Ledger, level: str
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(ledger.users[level])
        )

        assert response.status_code == 200, level


class TestHoldingABatchBackIsWhereTheLevelsPart:
    @pytest.mark.parametrize('level', ('admin', 'manager', 'user'))
    async def test_a_member_may_hold_a_batch_back(
        self, real_async_client: AsyncClient, ledger: _Ledger, level: str
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{ledger.lot_id}',
            json={'status': 'quarantined', 'reason': 'supplier notice 41/26'},
            headers=_auth(ledger.users[level]),
        )

        # An ordinary member holds the same `items:write` a manager does:
        # putting stock away and pulling it back are the same job.
        assert response.status_code == 200, (level, response.text)

    async def test_a_viewer_is_refused(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        response = await real_async_client.patch(
            f'/api/v1/stock-lots/{ledger.lot_id}',
            json={'status': 'quarantined', 'reason': 'supplier notice 41/26'},
            headers=_auth(ledger.users['viewer']),
        )

        assert response.status_code == 403


class TestWhatEachLevelActuallySees:
    @pytest.mark.parametrize('level', _LEVELS)
    async def test_the_ledger_carries_no_money_for_anybody(
        self, real_async_client: AsyncClient, ledger: _Ledger, level: str
    ) -> None:
        """The question the matrix was written for, answered on the screen.

        "Does a warehouseman see the costs" has no answer on this screen
        because there are no costs on it — not withheld from him, absent.
        The row is what moved, how much, between which places, under which
        batch, on whose authority.
        """
        response = await real_async_client.get(
            '/api/v1/stock-moves', headers=_auth(ledger.users[level])
        )

        row = response.json()['items'][0]
        # Named first, so "no money here" cannot be satisfied by an empty row.
        assert {'quantity', 'product_name', 'from_location_name', 'user_name'} <= set(
            row
        ), row
        assert not [
            field
            for field in row
            if any(word in field for word in ('cost', 'price', 'value'))
        ], row

    @pytest.mark.parametrize('level', _LEVELS)
    async def test_the_one_screen_that_shows_value_shows_it_to_everybody(
        self, real_async_client: AsyncClient, ledger: _Ledger, level: str
    ) -> None:
        """Including a viewer, deliberately and on the record.

        The report of stock on a given day is the only place in this family
        where money appears. Nothing withholds it by level today; that is a
        decision worth being able to point at rather than discover.
        """
        response = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(ledger.users[level]),
        )

        body = response.json()
        assert 'total_value' in body
        assert 'value' in body['items'][0]
