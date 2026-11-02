"""The two lookup reads a module's screens ask ``core_api.queries`` for.

Both exist because the alternative was reaching past the contract: a list
printing a partner's name beside a stored id, and a queue showing what a
document holds, each had to join core tables directly or walk the
entity-per-call namespaces one id at a time.

The reads are measured against the real PostgreSQL test DB, like
``tests/unit/test_db_utils.py`` beside them, because what is under test
is the SQL the read builds — its grouping, its sums and its organization
scope — which a stand-in session cannot answer for. The fixtures come
from the root ``conftest.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.models.user import User

pytestmark = pytest.mark.integration


async def _seed_hold(
    db: AsyncSession,
    user: User,
    *,
    organization_id: uuid.UUID,
    shelf_name: str,
    product_name: str,
    uom: Uom | None,
    document_id: uuid.UUID,
    quantities: tuple[str, ...],
) -> StockAnchor:
    """One document's reservations on one group of stock, as rows."""
    shelf = StorageLocation(
        organization_id=organization_id,
        created_by=user.id,
        name=shelf_name,
    )
    product = ProductTemplate(
        organization_id=organization_id,
        name=product_name,
        uom_id=uom.id if uom else None,
    )
    db.add_all([shelf, product])
    await db.flush()
    anchor = StockAnchor(
        organization_id=organization_id,
        product_template_id=product.id,
        storage_location_id=shelf.id,
    )
    db.add(anchor)
    await db.flush()
    db.add_all(
        [
            StockReservation(
                organization_id=organization_id,
                document_id=document_id,
                anchor_id=anchor.id,
                quantity=Decimal(quantity),
            )
            for quantity in quantities
        ]
    )
    await db.flush()
    return anchor


class TestPartnerDisplayNames:
    """core_api.queries.get_partner_display_names_async."""

    async def test_only_the_ids_asked_answer_with_their_own_names(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        """Every id asked for is answered; an id of nobody's is not there."""
        db = real_async_db_session
        active = Partner(
            organization_id=async_test_household.id,
            name='Northwind Trading',
            type='SUPPLIER',
        )
        retired = Partner(
            organization_id=async_test_household.id,
            name='Retired Vendor',
            type='SUPPLIER',
            is_active=False,
        )
        other_org = Organization(name='Names Elsewhere')
        db.add_all([active, retired, other_org])
        await db.flush()
        stranger = Partner(
            organization_id=other_org.id,
            name='Not Ours',
            type='SUPPLIER',
        )
        db.add(stranger)
        await db.flush()

        names = await core_api.queries.get_partner_display_names_async(
            db,
            async_test_household.id,
            [active.id, retired.id, stranger.id, uuid.uuid4()],
        )

        # A deactivated partner still answers: the name a document was
        # filed under is what its reader expects. A partner of another
        # organization, and an id that names nothing, answer not at all.
        assert names == {
            active.id: 'Northwind Trading',
            retired.id: 'Retired Vendor',
        }

    async def test_no_ids_asked_is_no_query_and_no_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        """An empty set of ids is answered with an empty mapping."""
        names = await core_api.queries.get_partner_display_names_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            partner_ids=[],
        )

        assert names == {}


class TestReservationsHeldByDocuments:
    """core_api.queries.get_reservations_held_by_documents_async."""

    async def test_holds_are_summed_per_document_product_and_shelf(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """Two rows on one group are one hold; each shelf keeps its own."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        category = UomCategory(organization_id=org_id, name='Count')
        db.add(category)
        await db.flush()
        uom = Uom(
            organization_id=org_id,
            category_id=category.id,
            name='Piece',
            symbol='pcs',
        )
        db.add(uom)
        await db.flush()

        receipt = uuid.uuid4()
        elsewhere = uuid.uuid4()
        on_receiving = await _seed_hold(
            db,
            async_test_user,
            organization_id=org_id,
            shelf_name='Receiving Bay',
            product_name='Shelf Bracket',
            uom=uom,
            document_id=receipt,
            quantities=('3', '2'),
        )
        on_hold = await _seed_hold(
            db,
            async_test_user,
            organization_id=org_id,
            shelf_name='Hold Shelf',
            product_name='Shelf Bracket',
            uom=uom,
            document_id=receipt,
            quantities=('1',),
        )
        await _seed_hold(
            db,
            async_test_user,
            organization_id=org_id,
            shelf_name='Dispatch Bench',
            product_name='Shelf Bracket',
            uom=uom,
            document_id=elsewhere,
            quantities=('7',),
        )

        holds = await core_api.queries.get_reservations_held_by_documents_async(
            db, org_id, [receipt]
        )

        by_shelf = {hold.location_id: hold for hold in holds}
        assert set(by_shelf) == {
            on_receiving.storage_location_id,
            on_hold.storage_location_id,
        }
        first = by_shelf[on_receiving.storage_location_id]
        # 3 + 2 on one group is one hold of 5, named in the same read.
        assert first.document_id == receipt
        assert first.product_template_id == on_receiving.product_template_id
        assert first.quantity == Decimal('5')
        assert first.product_name == 'Shelf Bracket'
        assert first.uom_symbol == 'pcs'
        assert first.location_name == 'Receiving Bay'
        assert by_shelf[on_hold.storage_location_id].quantity == Decimal('1')

        # The same document asked for twice is answered once, and a
        # document that holds nothing answers with nothing.
        both = await core_api.queries.get_reservations_held_by_documents_async(
            db, org_id, [receipt, receipt]
        )
        assert len(both) == 2
        nothing = await core_api.queries.get_reservations_held_by_documents_async(
            db, org_id, [uuid.uuid4()]
        )
        assert nothing == []

    async def test_a_hold_of_another_organization_is_not_named(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """A reservation of another organization naming this document stays out."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        receipt = uuid.uuid4()
        ours = await _seed_hold(
            db,
            async_test_user,
            organization_id=org_id,
            shelf_name='Receiving Bay',
            product_name='Shelf Bracket',
            uom=None,
            document_id=receipt,
            quantities=('4',),
        )

        other_org = Organization(name='Holds Elsewhere')
        db.add(other_org)
        await db.flush()
        stranger = await _seed_hold(
            db,
            async_test_user,
            organization_id=other_org.id,
            shelf_name='Stranger Shelf',
            product_name='Stranger Product',
            uom=None,
            document_id=receipt,
            quantities=('9',),
        )

        holds = await core_api.queries.get_reservations_held_by_documents_async(
            db, org_id, [receipt]
        )

        assert [hold.location_id for hold in holds] == [ours.storage_location_id]
        assert stranger.storage_location_id not in {hold.location_id for hold in holds}

    async def test_no_documents_asked_is_no_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """An empty set of documents is answered with an empty list."""
        holds = await core_api.queries.get_reservations_held_by_documents_async(
            db=real_async_db_session,
            organization_id=async_test_user.organization_id,
            document_ids=[],
        )

        assert holds == []
