"""Tests for the StockMove core model.

StockMove is the explicit WMS stock movement record (separate from
``ItemHistory`` which is a generic per-item audit log).  Every
``_post_the_change_async`` delta should create a StockMove so analytics
(aging, traceability, FIFO/FEFO history) can answer questions
that the implicit ItemHistory text log cannot.

Tests in this file exercise:
- Model instantiation and persistence
- DTO conversion (model → StockMoveDTO)
- Polymorphic reference (no FK on reference_id)
- External receipt (from=None, to=set) and external dispatch (from=set, to=None)
- Internal transfer (both set)
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.contracts import StockMoveDTO
from app.models.stock_move import (
    StockMove,
    StockMoveReferenceType,
    StockMoveState,
)
from app.models.storage_location import StorageLocation

from ._core_api_helpers import make_template


def _make_storage(
    db_session, org_id, user_id, storage_type, name: str
) -> StorageLocation:
    loc = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        storage_type_id=storage_type.id,
        name=name,
    )
    db_session.add(loc)
    db_session.flush()
    return loc


def _make_move(
    org_id,
    user_id,
    template_id,
    *,
    from_loc=None,
    to_loc=None,
    quantity: Decimal = Decimal('5.000'),
    state: str = StockMoveState.DONE,
    ref_type: str | None = StockMoveReferenceType.ADJUSTMENT,
    ref_id=None,
    lot_id=None,
) -> StockMove:
    return StockMove(
        organization_id=org_id,
        product_template_id=template_id,
        from_location_id=from_loc,
        to_location_id=to_loc,
        quantity=quantity,
        lot_id=lot_id,
        state=state,
        reference_type=ref_type,
        reference_id=ref_id,
        created_by=user_id,
    )


@pytest.mark.integration
class TestStockMoveModel:
    """StockMove model contract — persist, round-trip, validate."""

    def test_persist_external_receipt(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_type,
        test_storage_location,
    ):
        template = make_template(db_session, test_household.id)
        move = _make_move(
            test_household.id,
            test_user.id,
            template.id,
            from_loc=None,
            to_loc=test_storage_location.id,
        )
        db_session.add(move)
        db_session.commit()
        db_session.refresh(move)

        assert move.id is not None
        assert move.state == StockMoveState.DONE
        assert move.from_location_id is None
        assert move.to_location_id == test_storage_location.id
        assert move.quantity == Decimal('5.000')
        assert move.created_at is not None

    def test_persist_internal_transfer(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_type,
        test_storage_location,
    ):
        template = make_template(db_session, test_household.id)
        dest = _make_storage(
            db_session,
            test_household.id,
            test_user.id,
            test_storage_type,
            'Destination',
        )
        move = _make_move(
            test_household.id,
            test_user.id,
            template.id,
            from_loc=test_storage_location.id,
            to_loc=dest.id,
            quantity=Decimal('2.500'),
            ref_type=StockMoveReferenceType.DOCUMENT,
            ref_id=uuid4(),
        )
        db_session.add(move)
        db_session.commit()
        db_session.refresh(move)

        assert move.from_location_id == test_storage_location.id
        assert move.to_location_id == dest.id
        assert move.reference_type == StockMoveReferenceType.DOCUMENT
        assert move.reference_id is not None

    def test_polymorphic_reference_id_has_no_fk(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_location,
    ):
        """reference_id accepts any UUID; no FK enforces the target type."""
        template = make_template(db_session, test_household.id)
        fake_ref = uuid4()
        move = _make_move(
            test_household.id,
            test_user.id,
            template.id,
            to_loc=test_storage_location.id,
            ref_type=StockMoveReferenceType.DOCUMENT,
            ref_id=fake_ref,
        )
        db_session.add(move)
        db_session.commit()

        assert move.reference_id == fake_ref

    def test_query_moves_by_template(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_location,
    ):
        template = make_template(db_session, test_household.id)
        for qty in (Decimal('1'), Decimal('2'), Decimal('3')):
            move = _make_move(
                test_household.id,
                test_user.id,
                template.id,
                to_loc=test_storage_location.id,
                quantity=qty,
            )
            db_session.add(move)
        db_session.commit()

        rows = db_session.scalars(
            select(StockMove)
            .where(
                StockMove.organization_id == test_household.id,
                StockMove.product_template_id == template.id,
            )
            .order_by(StockMove.created_at)
        ).all()
        assert len(rows) == 3
        assert sum(r.quantity for r in rows) == Decimal('6')

    def test_dto_round_trip(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_location,
    ):
        template = make_template(db_session, test_household.id)
        move = _make_move(
            test_household.id,
            test_user.id,
            template.id,
            to_loc=test_storage_location.id,
        )
        db_session.add(move)
        db_session.commit()
        db_session.refresh(move)

        dto = StockMoveDTO.model_validate(move)
        assert dto.id == move.id
        assert dto.quantity == move.quantity
        assert dto.state == StockMoveState.DONE
        assert dto.reference_type == StockMoveReferenceType.ADJUSTMENT
        assert dto.from_location_id is None
        assert dto.to_location_id == test_storage_location.id

    def test_state_constant(self):
        """One state exists: every writer lands the row directly at done."""
        assert StockMoveState.DONE == 'done'
        assert not any(
            hasattr(StockMoveState, ghost)
            for ghost in ('DRAFT', 'CONFIRMED', 'ASSIGNED', 'CANCELLED')
        )

    def test_reference_type_constants(self):
        """The declared types are exactly the ones production writes."""
        assert StockMoveReferenceType.DOCUMENT == 'document'
        assert StockMoveReferenceType.ITEM == 'item'
        assert StockMoveReferenceType.ADJUSTMENT == 'adjustment'
        assert StockMoveReferenceType.MAKER_PRODUCTION == 'maker_production'
        assert StockMoveReferenceType.ITEM_HISTORY == 'item_history'
        assert not any(
            hasattr(StockMoveReferenceType, ghost) for ghost in ('MANUAL', 'TRANSFER')
        )

    def test_external_dispatch_allowed(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_location,
    ):
        """from_location_id set, to_location_id None = external dispatch."""
        template = make_template(db_session, test_household.id)
        move = _make_move(
            test_household.id,
            test_user.id,
            template.id,
            from_loc=test_storage_location.id,
            to_loc=None,
            quantity=Decimal('1'),
        )
        db_session.add(move)
        db_session.commit()
        db_session.refresh(move)
        assert move.to_location_id is None
        assert move.from_location_id == test_storage_location.id
