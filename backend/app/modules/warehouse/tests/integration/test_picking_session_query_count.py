"""A picking scan, completion and rollback must not query ``document_lines`` per line.

Receiving fetches every ``DocumentLine`` its scan can consult in one query
(``test_receiving_scan_query_count``). Picking looped a ``SELECT`` over the
pending lines, then over the picked ones, and did the same in the complete
and rollback loops, so the cost grew with the size of the session. The
document lines of a session are fetched once and matched in memory; the cost
is flat regardless of how many lines the session holds.
"""

from __future__ import annotations

import uuid
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.warehouse._picking_scan_ops import scan_pick_async
from app.modules.warehouse._wms_direction import PICKING
from app.modules.warehouse._wms_session_close import rollback_session_lines_async
from app.modules.warehouse._wms_session_ops import complete_session_async
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)

pytestmark = pytest.mark.integration


class _Seed:
    def __init__(
        self, session: WmsPickSession, hit_barcode: str, miss_barcode: str
    ) -> None:
        self.session = session
        self.hit_barcode = hit_barcode
        self.miss_barcode = miss_barcode


async def _seed_picking_session(
    db: AsyncSession,
    org_id: uuid.UUID,
    line_count: int,
    *,
    user_id: uuid.UUID,
    line_status: str = 'pending',
    first_pending: bool = False,
) -> _Seed:
    doc = Document(
        organization_id=org_id,
        type='OUT',
        number=f'PK-{uuid.uuid4().hex[:8]}',
        status=DocumentStatus.CONFIRMED.value,
        created_by=user_id,
    )
    db.add(doc)
    await db.flush()

    session = WmsPickSession(
        organization_id=org_id, document_id=doc.id, status='active'
    )
    db.add(session)
    await db.flush()

    miss_template = ProductTemplate(
        organization_id=org_id,
        name='Miss',
        barcode=f'BC-MISS-{uuid.uuid4().hex[:8]}',
    )
    db.add(miss_template)
    await db.flush()

    hit_template: ProductTemplate | None = None
    picked = line_status != 'pending'
    for i in range(line_count):
        template = ProductTemplate(
            organization_id=org_id,
            name=f'Line {i}',
            barcode=f'BC-HIT-{uuid.uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        doc_line = DocumentLine(
            document_id=doc.id,
            product_template_id=template.id,
            name=template.name,
            barcode=template.barcode,
            quantity=Decimal('10'),
            expected_quantity=Decimal('10'),
            done_quantity=Decimal('10') if picked else Decimal('0'),
        )
        db.add(doc_line)
        await db.flush()
        db.add(
            WmsPickLine(
                session_id=session.id,
                document_line_id=doc_line.id,
                pick_order=i,
                status='pending' if first_pending and i == 0 else line_status,
                picked_quantity=(
                    Decimal('10')
                    if picked and not (first_pending and i == 0)
                    else Decimal('0')
                ),
                expected_quantity=Decimal('10'),
                product_name=template.name,
                uom_symbol='pcs',
            )
        )
        if i == line_count - 1:
            hit_template = template
    await db.flush()

    assert hit_template is not None
    return _Seed(session, hit_template.barcode or '', miss_template.barcode or '')


async def _document_line_queries(
    db: AsyncSession, coro: Coroutine[Any, Any, Any]
) -> int:
    bind = db.get_bind()
    count = 0

    def _on_execute(
        _conn: object,
        _cursor: object,
        statement: object,
        _params: object,
        _ctx: object,
        _executemany: object,
    ) -> None:
        nonlocal count
        if 'FROM document_lines' in str(statement):
            count += 1

    event.listen(bind, 'before_cursor_execute', _on_execute)
    try:
        await coro
    finally:
        event.remove(bind, 'before_cursor_execute', _on_execute)
    return count


@pytest.mark.integration
@pytest.mark.asyncio
class TestPickingSessionQueryCount:
    async def test_missed_scan_reads_document_lines_once_per_set(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db, org = real_async_db_session, async_test_household.id
        small = await _seed_picking_session(db, org, 4, user_id=async_test_user.id)
        large = await _seed_picking_session(db, org, 8, user_id=async_test_user.id)

        small_count = await _document_line_queries(
            db, scan_pick_async(db, small.session.id, org, barcode=small.miss_barcode)
        )
        large_count = await _document_line_queries(
            db, scan_pick_async(db, large.session.id, org, barcode=large.miss_barcode)
        )

        # One for the pending lines, one for the already-resolved ones
        # (empty here, so its fetch is skipped by the caller).
        assert small_count == large_count
        assert large_count <= 2, f'got {large_count} document_lines queries'

    async def test_hit_scan_cost_is_flat_across_session_sizes(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db, org = real_async_db_session, async_test_household.id
        small = await _seed_picking_session(db, org, 4, user_id=async_test_user.id)
        large = await _seed_picking_session(db, org, 8, user_id=async_test_user.id)

        small_count = await _document_line_queries(
            db, scan_pick_async(db, small.session.id, org, barcode=small.hit_barcode)
        )
        large_count = await _document_line_queries(
            db, scan_pick_async(db, large.session.id, org, barcode=large.hit_barcode)
        )

        assert small_count == large_count, (
            f'a hit scan must cost the same regardless of session size: '
            f'{small_count} (4 lines) vs {large_count} (8 lines)'
        )

    async def test_scan_of_a_picked_product_cost_is_flat(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db, org = real_async_db_session, async_test_household.id
        small = await _seed_picking_session(
            db,
            org,
            4,
            user_id=async_test_user.id,
            line_status='picked',
            first_pending=True,
        )
        large = await _seed_picking_session(
            db,
            org,
            8,
            user_id=async_test_user.id,
            line_status='picked',
            first_pending=True,
        )

        small_count = await _document_line_queries(
            db, scan_pick_async(db, small.session.id, org, barcode=small.hit_barcode)
        )
        large_count = await _document_line_queries(
            db, scan_pick_async(db, large.session.id, org, barcode=large.hit_barcode)
        )

        assert small_count == large_count, (
            f'an already-picked scan must cost the same regardless of session '
            f'size: {small_count} (4 lines) vs {large_count} (8 lines)'
        )

    async def test_complete_cost_is_flat_across_session_sizes(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db, org = real_async_db_session, async_test_household.id
        small = await _seed_picking_session(
            db, org, 4, user_id=async_test_user.id, line_status='picked'
        )
        large = await _seed_picking_session(
            db, org, 8, user_id=async_test_user.id, line_status='picked'
        )

        small_count = await _document_line_queries(
            db, complete_session_async(db, PICKING, small.session.id, org)
        )
        large_count = await _document_line_queries(
            db, complete_session_async(db, PICKING, large.session.id, org)
        )

        assert small_count == large_count, (
            f'completing must cost the same regardless of session size: '
            f'{small_count} (4 lines) vs {large_count} (8 lines)'
        )

    async def test_rollback_cost_is_flat_across_session_sizes(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db, org = real_async_db_session, async_test_household.id
        small = await _seed_picking_session(
            db, org, 4, user_id=async_test_user.id, line_status='picked'
        )
        large = await _seed_picking_session(
            db, org, 8, user_id=async_test_user.id, line_status='picked'
        )

        small_count = await _document_line_queries(
            db, rollback_session_lines_async(db, small.session.id)
        )
        large_count = await _document_line_queries(
            db, rollback_session_lines_async(db, large.session.id)
        )

        assert small_count == large_count, (
            f'rolling back must cost the same regardless of session size: '
            f'{small_count} (4 lines) vs {large_count} (8 lines)'
        )
