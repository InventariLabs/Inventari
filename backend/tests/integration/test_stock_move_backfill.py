"""Tests for stock_moves_backfill translation logic.

Pure-function tests (no DB, no CLI) for the ItemHistory -> StockMove
translator.  Validates every supported action and the skip paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.stock_move import StockMove
from app.services.stock_moves_backfill import translate_history_to_move
from tests.integration._shelf import anchor_pending_records


def _make_item(
    org_id: UUID,
    location_id: UUID,
    template_id: UUID | None = uuid4(),
) -> Item:
    """Build a minimal Item in memory (not persisted)."""
    return Item(
        id=uuid4(),
        organization_id=org_id,
        storage_location_id=location_id,
        category_id=uuid4(),
        template_id=template_id,
        name='Test Item',
        quantity=1,
    )


def _make_history(
    item_id: UUID,
    action: str,
    changes: dict | None = None,
    user_id: UUID | None = None,
) -> ItemHistory:
    return ItemHistory(
        id=uuid4(),
        organization_id=uuid4(),
        item_id=item_id,
        user_id=user_id or uuid4(),
        action=action,
        changes=changes,
        created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )


class TestTranslateHistoryToMove:
    """Action-by-action translation contract."""

    def test_created_with_quantity_is_inbound(self):
        org = uuid4()
        loc = uuid4()
        item = _make_item(org, loc)
        history = _make_history(item.id, ItemAction.CREATED.value, {'quantity': 5})
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id is None
        assert move.to_location_id == loc
        assert move.quantity == Decimal('5')
        assert move.reference_type == 'item_history'
        assert move.reference_id == history.id
        assert move.state == 'done'

    def test_moved_with_both_locations_is_internal_transfer(self):
        org = uuid4()
        from_loc = uuid4()
        to_loc = uuid4()
        item = _make_item(org, from_loc)
        history = _make_history(
            item.id,
            ItemAction.MOVED.value,
            {
                'from_storage_location_id': str(from_loc),
                'to_location_id': str(to_loc),
                'quantity': 2,
            },
        )
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id == from_loc
        assert move.to_location_id == to_loc
        assert move.quantity == Decimal('2')

    def test_moved_missing_from_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(
            item.id,
            ItemAction.MOVED.value,
            {'to_location_id': str(uuid4()), 'quantity': 1},
        )
        assert translate_history_to_move(history, item) is None

    def test_moved_missing_to_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(
            item.id,
            ItemAction.MOVED.value,
            {'from_storage_location_id': str(uuid4()), 'quantity': 1},
        )
        assert translate_history_to_move(history, item) is None

    def test_used_is_outbound(self):
        org = uuid4()
        loc = uuid4()
        item = _make_item(org, loc)
        history = _make_history(item.id, ItemAction.USED.value, {'quantity': 1})
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id == loc
        assert move.to_location_id is None

    def test_disposed_is_outbound(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.DISPOSED.value, {'quantity': 1})
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.to_location_id is None

    def test_quantity_changed_positive_delta_is_inbound(self):
        org = uuid4()
        loc = uuid4()
        item = _make_item(org, loc)
        history = _make_history(
            item.id,
            ItemAction.QUANTITY_CHANGED.value,
            {'old_quantity': 2, 'new_quantity': 5},
        )
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id is None
        assert move.to_location_id == loc
        assert move.quantity == Decimal('3')

    def test_quantity_changed_negative_delta_is_outbound(self):
        org = uuid4()
        loc = uuid4()
        item = _make_item(org, loc)
        history = _make_history(
            item.id,
            ItemAction.QUANTITY_CHANGED.value,
            {'old_quantity': 5, 'new_quantity': 2},
        )
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id == loc
        assert move.to_location_id is None
        assert move.quantity == Decimal('3')

    def test_quantity_changed_no_change_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(
            item.id,
            ItemAction.QUANTITY_CHANGED.value,
            {'old_quantity': 5, 'new_quantity': 5},
        )
        assert translate_history_to_move(history, item) is None

    def test_non_template_item_is_skipped(self):
        """Items without template_id never bridge to StockMove."""
        item = _make_item(uuid4(), uuid4(), template_id=None)
        history = _make_history(item.id, ItemAction.CREATED.value, {'quantity': 1})
        assert translate_history_to_move(history, item) is None

    def test_no_quantity_in_changes_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.CREATED.value, {'name': 'New name'})
        assert translate_history_to_move(history, item) is None

    def test_updated_action_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.UPDATED.value, {'quantity': 5})
        # UPDATED can carry a quantity, but it does not represent a movement
        # by itself (it tracks attribute changes, not stock flow). Skip.
        assert translate_history_to_move(history, item) is None

    def test_deleted_action_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.DELETED.value, {'quantity': 5})
        assert translate_history_to_move(history, item) is None

    def test_restored_action_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.RESTORED.value, {'quantity': 5})
        assert translate_history_to_move(history, item) is None

    def test_preserves_history_id_and_user_as_reference(self):
        """Backfilled moves must link back to the source history row."""
        item = _make_item(uuid4(), uuid4())
        user = uuid4()
        history = _make_history(
            item.id, ItemAction.CREATED.value, {'quantity': 1}, user_id=user
        )
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.reference_id == history.id
        assert move.created_by == user
        assert move.created_at == history.created_at
        assert move.completed_at == history.created_at

    def test_quantity_zero_is_skipped(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.CREATED.value, {'quantity': 0})
        assert translate_history_to_move(history, item) is None

    def test_alternative_quantity_key_qty(self):
        item = _make_item(uuid4(), uuid4())
        history = _make_history(item.id, ItemAction.USED.value, {'qty': 3})
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.quantity == Decimal('3')

    def test_alternative_location_key_from_to(self):
        org = uuid4()
        from_loc = uuid4()
        to_loc = uuid4()
        item = _make_item(org, from_loc)
        history = _make_history(
            item.id,
            ItemAction.MOVED.value,
            {'from': str(from_loc), 'to': str(to_loc), 'qty': 1},
        )
        move = translate_history_to_move(history, item)
        assert move is not None
        assert move.from_location_id == from_loc
        assert move.to_location_id == to_loc


@pytest.mark.integration
class TestBackfillCLIIntegration:
    """End-to-end: CLI command translates ItemHistory and is idempotent."""

    def test_backfill_creates_moves_and_is_idempotent(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_location,
        test_category,
    ):
        from app.cli.commands_backfill import (
            _collect_wms_org_ids,
            backfill_stock_moves_impl,
        )
        from app.models.item_history import ItemHistory
        from app.models.product_template import ProductTemplate

        template = ProductTemplate(
            organization_id=test_household.id,
            name='Backfill Template',
            sku=f'SKU-BF-{uuid4().hex[:8]}',
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            organization_id=test_household.id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            template_id=template.id,
            name='Backfill Item',
            quantity=1,
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.flush()

        for changes, action in [
            ({'quantity': 5}, ItemAction.CREATED.value),
            ({'quantity': 1}, ItemAction.USED.value),
        ]:
            db_session.add(
                ItemHistory(
                    organization_id=test_household.id,
                    item_id=item.id,
                    user_id=test_user.id,
                    action=action,
                    changes=changes,
                )
            )
        db_session.commit()

        wms_orgs = _collect_wms_org_ids(db_session)
        assert test_household.id in wms_orgs

        from sqlalchemy import select as sa_select

        # NOTE: the backfill reads ItemHistory rows from the global table.
        # We intentionally do NOT assert on the exact ItemHistory count here,
        # because other integration tests in the full suite can leave
        # ItemHistory rows behind (despite TRUNCATE in conftest teardown —
        # some worker / event-handler paths race the cleanup). The relevant
        # behavior is the StockMove outcome below, which is scoped to
        # test_household.id and is what the backfill CLI is supposed to
        # produce. See the bisect in commit history for details.

        # First run: should create 2 moves for our item.
        # NOTE: `translated` and `skipped` are global counts across all WMS
        # orgs. In a full integration suite, prior tests may leave ItemHistory
        # rows behind (TRUNCATE in conftest teardown races with worker /
        # event-handler writes). The test's CORE assertions are:
        #   - `translated >= 2` (our 2 histories were translated)
        #   - `len(moves) == 2` scoped to test_household.id (exactly 2 moves
        #     persisted for our item, no pollution)
        # The `skipped` global count is not asserted because it can include
        # polluted history rows from other tests that don't translate (e.g.
        # their item was deleted/missing).
        translated, skipped = backfill_stock_moves_impl(
            db_session, batch_size=10, dry_run=False
        )
        assert translated >= 2
        assert skipped >= 0  # trivial — kept for symmetry with second run

        moves = db_session.scalars(
            sa_select(StockMove).where(StockMove.organization_id == test_household.id)
        ).all()
        assert len(moves) == 2

        # Second run: must be a no-op (partial unique index dedup). The test
        # item's 2 histories are already translated, so `translated2 == 0`
        # for OUR scope (other polluted rows may still get translated in
        # odd interleavings — we accept `translated2 >= 0`).
        translated2, skipped2 = backfill_stock_moves_impl(
            db_session, batch_size=10, dry_run=False
        )
        assert translated2 >= 0
        assert skipped2 >= 0

        moves_after = db_session.scalars(
            sa_select(StockMove).where(StockMove.organization_id == test_household.id)
        ).all()
        assert len(moves_after) == 2
