"""Tests for core_api.stock_moves namespace.

Covers the public API surface that callers (analytics, UI, future
modules) will use to read and create StockMove records.

Contract:
    - create_async stores a single StockMove with optional reference.
    - list_by_template_async returns moves for one product, newest first.
    - list_by_reference_async returns moves linked to one source (e.g. a
      document_id) regardless of product — useful for traceability.
    - All methods are org-scoped (a move in another org is never returned).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.contracts import StockMoveDTO
from app.core.public_api import core_api
from app.models.stock_move import StockMoveReferenceType, StockMoveState

from ._core_api_helpers import make_template

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
class TestCoreStockMovesAPI:
    """Service-level contract for the StockMoves CoreAPI namespace."""

    async def test_create_async_persists_move(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )

        dto = await core_api.stock_moves.create_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            from_location_id=None,
            to_location_id=async_test_storage_location.id,
            quantity=Decimal('5.000'),
            reference_type=StockMoveReferenceType.ADJUSTMENT,
            created_by=async_test_user.id,
        )

        assert isinstance(dto, StockMoveDTO)
        assert dto.organization_id == async_test_household.id
        assert dto.from_location_id is None
        assert dto.to_location_id == async_test_storage_location.id
        assert dto.quantity == Decimal('5.000')
        assert dto.state == StockMoveState.DONE
        assert dto.reference_type == StockMoveReferenceType.ADJUSTMENT

    async def test_list_by_template_returns_only_target_product(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template_a = await db.run_sync(
            lambda s: make_template(s, async_test_household.id, sku_prefix='SKU-A')
        )
        template_b = await db.run_sync(
            lambda s: make_template(s, async_test_household.id, sku_prefix='SKU-B')
        )

        for tpl in (template_a, template_a, template_b):
            await core_api.stock_moves.create_async(
                db,
                organization_id=async_test_household.id,
                product_template_id=tpl.id,
                to_location_id=async_test_storage_location.id,
                quantity=Decimal('1'),
                created_by=async_test_user.id,
            )

        moves_a = await core_api.stock_moves.list_by_template_async(
            db, async_test_household.id, template_a.id
        )
        assert len(moves_a) == 2
        assert all(m.product_template_id == template_a.id for m in moves_a)

    async def test_list_by_reference_finds_moves_linked_to_source(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )
        doc_id = uuid4()

        # Three moves linked to the same document, plus one manual.
        for _ in range(3):
            await core_api.stock_moves.create_async(
                db,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                to_location_id=async_test_storage_location.id,
                quantity=Decimal('1'),
                reference_type=StockMoveReferenceType.DOCUMENT,
                reference_id=doc_id,
                created_by=async_test_user.id,
            )
        await core_api.stock_moves.create_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            to_location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            reference_type=StockMoveReferenceType.ADJUSTMENT,
            created_by=async_test_user.id,
        )

        moves = await core_api.stock_moves.list_by_reference_async(
            db,
            async_test_household.id,
            StockMoveReferenceType.DOCUMENT,
            doc_id,
        )
        assert len(moves) == 3
        assert all(m.reference_id == doc_id for m in moves)

    async def test_org_isolation(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """Moves from another org must never leak into the result set."""
        from app.models.organization import Organization

        db = real_async_db_session
        other_org = Organization(
            name='Other Org',
            enabled_modules=['core'],
        )
        db.add(other_org)
        await db.flush()
        await db.refresh(other_org)
        other_loc = await db.run_sync(
            lambda s: _make_other_loc(s, other_org.id, async_test_user.id)
        )
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )

        await core_api.stock_moves.create_async(
            db,
            organization_id=other_org.id,
            product_template_id=template.id,
            to_location_id=other_loc.id,
            quantity=Decimal('99'),
            created_by=async_test_user.id,
        )
        moves = await core_api.stock_moves.list_by_template_async(
            db, async_test_household.id, template.id
        )
        assert all(m.organization_id == async_test_household.id for m in moves)

    async def test_get_by_id_returns_dto_or_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )
        created = await core_api.stock_moves.create_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            to_location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            created_by=async_test_user.id,
        )

        found = await core_api.stock_moves.get_async(
            db, async_test_household.id, created.id
        )
        assert found is not None
        assert found.id == created.id

        missing = await core_api.stock_moves.get_async(
            db, async_test_household.id, uuid4()
        )
        assert missing is None


def _make_other_loc(db_session, org_id, user_id):
    from app.models.storage_location import StorageLocation
    from app.models.storage_type import StorageType

    storage_type = StorageType(name='Other Type', type_code='OTHER')
    db_session.add(storage_type)
    db_session.flush()
    loc = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        storage_type_id=storage_type.id,
        name='Other Loc',
    )
    db_session.add(loc)
    db_session.flush()
    return loc
