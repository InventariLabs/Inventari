"""The lookup and ledger reads the warehouse's own screens ask Core for.

Three questions the warehouse used to answer by joining Core's tables: the
name of the partners a document search matches, the name of the shelves a
register groups by, and whether stock a posted line put on a shelf has left
it since. Each is measured here against the real PostgreSQL test DB, because
what is under test is the SQL the read builds — its organization scope, its
null-safe grouping and the reference it excludes — which a stand-in session
cannot answer for. The fixtures come from the root ``conftest.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockMoveReferenceType, StockMoveState
from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration


async def _shelf(
    db: AsyncSession, user: User, org_id: uuid.UUID, name: str
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=user.id,
        name=name,
    )
    db.add(shelf)
    await db.flush()
    return shelf


class TestPartnerIdsNamedLike:
    """core_api.partners.ids_named_like_async."""

    async def test_only_this_organizations_matching_names_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        """Case does not matter, inactive answers, a stranger does not."""
        db = real_async_db_session
        org_id = async_test_household.id
        active = Partner(
            organization_id=org_id,
            name='Northwind Trading',
            type='SUPPLIER',
        )
        retired = Partner(
            organization_id=org_id,
            name='Old Northwind Depot',
            type='SUPPLIER',
            is_active=False,
        )
        unrelated = Partner(
            organization_id=org_id,
            name='Southgate Foods',
            type='CUSTOMER',
        )
        other_org = Organization(name='Partners Elsewhere')
        db.add_all([active, retired, unrelated, other_org])
        await db.flush()
        stranger = Partner(
            organization_id=other_org.id,
            name='Northwind Abroad',
            type='SUPPLIER',
        )
        db.add(stranger)
        await db.flush()

        ids = await core_api.partners.ids_named_like_async(db, org_id, 'northwind')

        assert set(ids) == {active.id, retired.id}

    async def test_a_wildcard_in_the_term_matches_itself(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        """``%`` and ``_`` in the search are text, not SQL patterns."""
        db = real_async_db_session
        org_id = async_test_household.id
        percent = Partner(
            organization_id=org_id,
            name='100% Organic',
            type='SUPPLIER',
        )
        plain = Partner(
            organization_id=org_id,
            name='100 Percent Organic',
            type='SUPPLIER',
        )
        db.add_all([percent, plain])
        await db.flush()

        ids = await core_api.partners.ids_named_like_async(db, org_id, '100%')

        assert ids == [percent.id]


class TestStorageDisplayNames:
    """core_api.queries.get_storage_display_names_async."""

    async def test_names_only_this_organizations_shelves(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """An archived shelf still answers; a foreign or unknown id does not."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        open_shelf = await _shelf(db, async_test_user, org_id, 'Receiving Bay')
        archived = await _shelf(db, async_test_user, org_id, 'Old Overspill')
        archived.settings = {'archived': True}
        await db.flush()

        other_org = Organization(name='Shelves Elsewhere')
        db.add(other_org)
        await db.flush()
        stranger = await _shelf(db, async_test_user, other_org.id, 'Not Ours')
        await db.flush()

        names = await core_api.queries.get_storage_display_names_async(
            db,
            org_id,
            [open_shelf.id, archived.id, stranger.id, uuid.uuid4()],
        )

        assert names == {
            open_shelf.id: 'Receiving Bay',
            archived.id: 'Old Overspill',
        }

    async def test_no_ids_asked_is_no_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        names = await core_api.queries.get_storage_display_names_async(
            real_async_db_session, async_test_household.id, []
        )

        assert names == {}


class TestAnyDeparture:
    """core_api.stock_moves.any_departure_async."""

    async def test_a_later_move_off_the_shelf_is_a_departure(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, async_test_user, org_id, 'Receiving Bay')
        destination = await _shelf(db, async_test_user, org_id, 'Aisle One')
        product = ProductTemplate(organization_id=org_id, name='Shelf Bracket')
        db.add(product)
        await db.flush()
        landed = datetime.now(UTC) - timedelta(hours=2)
        db.add(
            StockMove(
                organization_id=org_id,
                product_template_id=product.id,
                from_location_id=shelf.id,
                to_location_id=destination.id,
                quantity=Decimal('2'),
                state=StockMoveState.DONE.value,
                created_at=landed + timedelta(hours=1),
            )
        )
        await db.flush()

        assert (
            await core_api.stock_moves.any_departure_async(
                db,
                org_id,
                product_template_id=product.id,
                from_location_id=shelf.id,
                lot_id=None,
                owner_id=None,
                since=landed,
            )
            is True
        )
        # A movement before the goods landed is not a departure since.
        assert (
            await core_api.stock_moves.any_departure_async(
                db,
                org_id,
                product_template_id=product.id,
                from_location_id=shelf.id,
                lot_id=None,
                owner_id=None,
                since=landed + timedelta(hours=2),
            )
            is False
        )

    async def test_an_excluded_restatement_is_not_a_departure(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """A correction of the original does not count as stock used."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, async_test_user, org_id, 'Receiving Bay')
        destination = await _shelf(db, async_test_user, org_id, 'Aisle One')
        product = ProductTemplate(organization_id=org_id, name='Shelf Bracket')
        db.add(product)
        await db.flush()
        landed = datetime.now(UTC) - timedelta(hours=2)
        correction = uuid.uuid4()
        db.add(
            StockMove(
                organization_id=org_id,
                product_template_id=product.id,
                from_location_id=shelf.id,
                to_location_id=destination.id,
                quantity=Decimal('2'),
                state=StockMoveState.DONE.value,
                reference_type=StockMoveReferenceType.DOCUMENT.value,
                reference_id=correction,
                created_at=landed + timedelta(hours=1),
            )
        )
        await db.flush()

        question = {
            'product_template_id': product.id,
            'from_location_id': shelf.id,
            'lot_id': None,
            'owner_id': None,
            'since': landed,
        }
        assert (
            await core_api.stock_moves.any_departure_async(
                db, org_id, excluded_reference_ids=[correction], **question
            )
            is False
        )
        assert (
            await core_api.stock_moves.any_departure_async(
                db, org_id, excluded_reference_ids=[uuid.uuid4()], **question
            )
            is True
        )

    async def test_another_group_or_organization_does_not_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """Same product, another shelf — and the same shelf in another org."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, async_test_user, org_id, 'Receiving Bay')
        elsewhere = await _shelf(db, async_test_user, org_id, 'Aisle One')
        product = ProductTemplate(organization_id=org_id, name='Shelf Bracket')
        db.add(product)
        await db.flush()
        landed = datetime.now(UTC) - timedelta(hours=2)
        db.add_all(
            [
                StockMove(
                    organization_id=org_id,
                    product_template_id=product.id,
                    from_location_id=elsewhere.id,
                    to_location_id=shelf.id,
                    quantity=Decimal('2'),
                    state=StockMoveState.DONE.value,
                    created_at=landed + timedelta(hours=1),
                ),
                StockMove(
                    organization_id=org_id,
                    product_template_id=product.id,
                    from_location_id=shelf.id,
                    to_location_id=elsewhere.id,
                    quantity=Decimal('2'),
                    state=StockMoveState.DONE.value,
                    owner_id=None,
                    created_at=landed + timedelta(hours=1),
                ),
            ]
        )
        await db.flush()
        other_org = Organization(name='Stock Elsewhere')
        db.add(other_org)
        await db.flush()
        foreign_shelf = await _shelf(db, async_test_user, other_org.id, 'Their Bay')
        foreign_product = ProductTemplate(
            organization_id=other_org.id, name='Shelf Bracket'
        )
        db.add(foreign_product)
        await db.flush()
        db.add(
            StockMove(
                organization_id=other_org.id,
                product_template_id=foreign_product.id,
                from_location_id=foreign_shelf.id,
                to_location_id=foreign_shelf.id,
                quantity=Decimal('2'),
                state=StockMoveState.DONE.value,
                created_at=landed + timedelta(hours=1),
            )
        )
        await db.flush()

        # The shelf is not the one asked about...
        assert (
            await core_api.stock_moves.any_departure_async(
                db,
                org_id,
                product_template_id=product.id,
                from_location_id=uuid.uuid4(),
                lot_id=None,
                owner_id=None,
                since=landed,
            )
            is False
        )
        # ...and this organization's shelf does answer for its own move.
        assert (
            await core_api.stock_moves.any_departure_async(
                db,
                org_id,
                product_template_id=product.id,
                from_location_id=shelf.id,
                lot_id=None,
                owner_id=None,
                since=landed,
            )
            is True
        )


class TestPostedGroups:
    """core_api.stock_moves.posted_groups_async."""

    async def test_one_row_per_group_the_document_filled(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """Product, shelf, batch and owner name a group; the last landing dates it.

        The same group filled twice is one row, dated by the later landing —
        that is the moment a later departure is compared with. A departure
        (no destination), a movement that has not landed and another
        document's movements are not groups this document filled, and
        neither is a movement in another organization.
        """
        db = real_async_db_session
        org_id = async_test_user.organization_id
        product = ProductTemplate(organization_id=org_id, name='Shelf Bracket')
        other_product = ProductTemplate(organization_id=org_id, name='Shelf Pin')
        db.add_all([product, other_product])
        await db.flush()
        receiving = await _shelf(db, async_test_user, org_id, 'Receiving Bay')
        overspill = await _shelf(db, async_test_user, org_id, 'Old Overspill')
        lot = StockLot(
            organization_id=org_id,
            product_template_id=product.id,
            name='Batch A',
        )
        owner = Partner(
            organization_id=org_id, name='Consignment Owner', type='SUPPLIER'
        )
        db.add_all([lot, owner])
        await db.flush()
        document_id = uuid.uuid4()
        first = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
        later = first + timedelta(hours=1)

        def landed(
            *,
            product_template_id: uuid.UUID = product.id,
            to_location_id: uuid.UUID | None = receiving.id,
            lot_id: uuid.UUID | None = None,
            owner_id: uuid.UUID | None = None,
            reference_id: uuid.UUID = document_id,
            state: str = StockMoveState.DONE.value,
            created_at: datetime = first,
            from_location_id: uuid.UUID | None = None,
        ) -> StockMove:
            return StockMove(
                organization_id=org_id,
                product_template_id=product_template_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                lot_id=lot_id,
                owner_id=owner_id,
                quantity=Decimal('2'),
                state=state,
                reference_type=StockMoveReferenceType.DOCUMENT.value,
                reference_id=reference_id,
                created_at=created_at,
            )

        db.add_all(
            [
                landed(),
                landed(created_at=later),
                landed(lot_id=lot.id, created_at=later),
                landed(to_location_id=overspill.id),
                landed(owner_id=owner.id),
                landed(product_template_id=other_product.id),
                # Not a landing: stock left the shelf, or never arrived.
                landed(from_location_id=receiving.id, to_location_id=None),
                landed(state='void'),
                # Another document's movement is not this document's group.
                landed(reference_id=uuid.uuid4()),
            ]
        )
        await db.flush()
        other_org = Organization(name='Groups Elsewhere')
        db.add(other_org)
        await db.flush()
        foreign_shelf = await _shelf(db, async_test_user, other_org.id, 'Their Bay')
        foreign_product = ProductTemplate(
            organization_id=other_org.id, name='Shelf Bracket'
        )
        db.add(foreign_product)
        await db.flush()
        db.add(
            StockMove(
                organization_id=other_org.id,
                product_template_id=foreign_product.id,
                to_location_id=foreign_shelf.id,
                quantity=Decimal('2'),
                state=StockMoveState.DONE.value,
                reference_type=StockMoveReferenceType.DOCUMENT.value,
                reference_id=document_id,
                created_at=later,
            )
        )
        await db.flush()

        groups = await core_api.stock_moves.posted_groups_async(
            db,
            org_id,
            StockMoveReferenceType.DOCUMENT.value,
            document_id,
        )

        assert {
            (g.product_template_id, g.to_location_id, g.lot_id, g.owner_id): g.posted_at
            for g in groups
        } == {
            (product.id, receiving.id, None, None): later,
            (product.id, receiving.id, lot.id, None): later,
            (product.id, receiving.id, None, owner.id): first,
            (product.id, overspill.id, None, None): first,
            (other_product.id, receiving.id, None, None): first,
        }

    async def test_a_document_that_filled_nothing_has_no_groups(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        assert (
            await core_api.stock_moves.posted_groups_async(
                real_async_db_session,
                async_test_household.id,
                StockMoveReferenceType.DOCUMENT.value,
                uuid.uuid4(),
            )
            == []
        )
