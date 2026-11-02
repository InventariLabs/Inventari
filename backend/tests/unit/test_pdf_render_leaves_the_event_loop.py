"""WeasyPrint is CPU-bound and synchronous: a request that renders a PDF must
do it in a worker thread, or every other request on the same worker waits."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.core.contracts import StockAsOfReportDTO
from app.modules.purchase_orders import po_pdf_service
from app.services import stock_report_pdf_service as stock_svc


def _record_render_thread(
    monkeypatch: pytest.MonkeyPatch, svc: Any
) -> list[threading.Thread]:
    seen: list[threading.Thread] = []

    def render(html: str) -> bytes:
        seen.append(threading.current_thread())
        return b'%PDF'

    monkeypatch.setattr(svc, 'render_to_pdf', render)
    return seen


@pytest.mark.anyio
async def test_stock_as_of_pdf_renders_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_issuer(organization: Any, lang: str = 'en') -> Any:
        return SimpleNamespace(name='Acme', logo_data_uri=None)

    monkeypatch.setattr(stock_svc, 'build_issuer_context', no_issuer)
    monkeypatch.setattr(stock_svc, 'page_size_of', lambda organization: 'A4')
    seen = _record_render_thread(monkeypatch, stock_svc._svc)
    report = StockAsOfReportDTO(
        as_of=datetime(2026, 9, 30, tzinfo=UTC),
        generated_at=datetime(2026, 10, 2, tzinfo=UTC),
        complete_from=datetime(2026, 9, 30, tzinfo=UTC),
        organization_name='Whatever Warehouse',
        currency='USD',
        items=[],
        total_value=Decimal('0'),
    )

    pdf = await stock_svc.generate_stock_as_of_pdf(
        report, SimpleNamespace(country=None), 'en'
    )

    assert pdf == b'%PDF'
    assert seen and seen[0] is not threading.main_thread()


@pytest.mark.anyio
async def test_purchase_order_pdf_renders_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_render_thread(monkeypatch, po_pdf_service._svc)
    po = SimpleNamespace(
        id=uuid4(),
        number='PO/2025/0007',
        currency='PLN',
        status='DRAFT',
        scheduled_date=None,
        created_at=datetime(2026, 1, 1),
        notes=None,
        partner=SimpleNamespace(name='Supplier A', tax_id=None, address=None),
        organization=SimpleNamespace(name='Acme Sp. z o.o.'),
        lines=[],
    )

    pdf = await po_pdf_service.generate_po_pdf(po, lang='en')  # type: ignore[arg-type]

    assert pdf == b'%PDF'
    assert seen and seen[0] is not threading.main_thread()
