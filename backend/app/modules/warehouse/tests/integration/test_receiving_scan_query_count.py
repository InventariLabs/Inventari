"""a receiving scan must not query ``document_lines`` per session line.

Before the fix a hit cost one ``SELECT`` per pending line up to the match,
and a miss repeated the pattern over the already-received lines. The scan
loop should fetch every ``DocumentLine`` once and match in memory, so the
cost is flat regardless of session size and of whether the scan hits.
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
from app.modules.warehouse._receiving_scan_ops import scan_receive_async
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)

pytestmark = pytest.mark.integration


class _SeedResult:
    def __init__(
        self,
        session: WmsPickSession,
        hit_barcode: str,
        miss_barcode: str,
    ) -> None:
        self.session = session
        self.hit_barcode = hit_barcode
        self.miss_barcode = miss_barcode


async def _seed_receiving_session(
    db: AsyncSession,
    org_id: uuid.UUID,
    line_count: int,
    *,
    user_id: uuid.UUID,
) -> _SeedResult:
    doc = Document(
        organization_id=org_id,
        type='IN',
        number=f'RC-{uuid.uuid4().hex[:8]}',
        status=DocumentStatus.CONFIRMED.value,
        created_by=user_id,
    )
    db.add(doc)
    await db.flush()

    session = WmsPickSession(
        organization_id=org_id,
        document_id=doc.id,
        status='active',
    )
    db.add(session)
    await db.flush()

    hit_template: ProductTemplate | None = None
    miss_template = ProductTemplate(
        organization_id=org_id,
        name='Miss',
        barcode=f'BC-MISS-{uuid.uuid4().hex[:8]}',
    )
    db.add(miss_template)
    await db.flush()

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
            done_quantity=Decimal('0'),
        )
        db.add(doc_line)
        await db.flush()
        db.add(
            WmsPickLine(
                session_id=session.id,
                document_line_id=doc_line.id,
                pick_order=i,
                status='pending',
                picked_quantity=Decimal('0'),
                expected_quantity=Decimal('10'),
                product_name=template.name,
                uom_symbol='pcs',
            )
        )
        if i == 1:
            hit_template = template
    await db.flush()

    assert hit_template is not None
    return _SeedResult(
        session=session,
        hit_barcode=hit_template.barcode or '',
        miss_barcode=miss_template.barcode or '',
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestReceivingScanQueryCount:
    async def _count_queries(
        self, db: AsyncSession, coro: Coroutine[Any, Any, Any]
    ) -> tuple[int, int]:
        bind = db.get_bind()
        counts = {'total': 0, 'document_lines': 0}

        def _on_execute(
            _conn: object,
            _cursor: object,
            statement: object,
            _params: object,
            _ctx: object,
            _executemany: object,
        ) -> None:
            counts['total'] += 1
            if 'FROM document_lines' in str(statement):
                counts['document_lines'] += 1

        event.listen(bind, 'before_cursor_execute', _on_execute)
        try:
            await coro
        finally:
            event.remove(bind, 'before_cursor_execute', _on_execute)
        return counts['total'], counts['document_lines']

    async def test_miss_cost_is_flat_across_session_sizes(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        small = await _seed_receiving_session(
            db, async_test_household.id, 4, user_id=async_test_user.id
        )
        large = await _seed_receiving_session(
            db, async_test_household.id, 8, user_id=async_test_user.id
        )

        small_total, small_doc_lines = await self._count_queries(
            db,
            scan_receive_async(
                db,
                small.session.id,
                async_test_household.id,
                barcode=small.miss_barcode,
            ),
        )
        large_total, large_doc_lines = await self._count_queries(
            db,
            scan_receive_async(
                db,
                large.session.id,
                async_test_household.id,
                barcode=large.miss_barcode,
            ),
        )

        assert small_doc_lines == 1, (
            f'expected 1 document_lines query, got {small_doc_lines}'
        )
        assert large_doc_lines == 1, (
            f'expected 1 document_lines query, got {large_doc_lines}'
        )
        assert small_total == large_total, (
            f'a missed scan must cost the same regardless of session size: '
            f'{small_total} (4 lines) vs {large_total} (8 lines)'
        )

    async def test_hit_cost_is_flat_across_session_sizes(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        small = await _seed_receiving_session(
            db, async_test_household.id, 4, user_id=async_test_user.id
        )
        large = await _seed_receiving_session(
            db, async_test_household.id, 8, user_id=async_test_user.id
        )

        small_total, small_doc_lines = await self._count_queries(
            db,
            scan_receive_async(
                db, small.session.id, async_test_household.id, barcode=small.hit_barcode
            ),
        )
        large_total, large_doc_lines = await self._count_queries(
            db,
            scan_receive_async(
                db, large.session.id, async_test_household.id, barcode=large.hit_barcode
            ),
        )

        # Constant: the scan batch fetch, the delete-orphan cascade reload
        # of ``Document.lines`` on flush, and the one reload in
        # ``_execute_receive`` — none of them depend on session size.
        assert small_doc_lines == 3, (
            f'expected 3 document_lines queries, got {small_doc_lines}'
        )
        assert large_doc_lines == 3, (
            f'expected 3 document_lines queries, got {large_doc_lines}'
        )
        assert small_total == large_total, (
            f'a hit scan must cost the same regardless of session size: '
            f'{small_total} (4 lines) vs {large_total} (8 lines)'
        )
