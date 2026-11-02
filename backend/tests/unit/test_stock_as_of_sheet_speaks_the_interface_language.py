"""The stock-on-a-day sheet words and dates itself like the screen does."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.contracts import StockAsOfReportDTO
from app.services import stock_report_pdf_service as svc


def _report() -> StockAsOfReportDTO:
    return StockAsOfReportDTO(
        as_of=datetime(2026, 9, 30, tzinfo=UTC),
        generated_at=datetime(2026, 10, 2, tzinfo=UTC),
        complete_from=datetime(2026, 9, 30, tzinfo=UTC),
        organization_name='Whatever Warehouse',
        currency='USD',
        items=[],
        total_value=Decimal('0'),
    )


async def _sheet_html(
    monkeypatch: pytest.MonkeyPatch, lang: str, country: str | None = None
) -> str:
    async def no_issuer(organization: Any, lang: str = 'en') -> Any:
        return SimpleNamespace(name='Acme', logo_data_uri=None)

    monkeypatch.setattr(svc, 'build_issuer_context', no_issuer)
    monkeypatch.setattr(svc, 'page_size_of', lambda organization: 'A4')
    monkeypatch.setattr(svc._svc, 'render_to_pdf', lambda html: html.encode())
    pdf = await svc.generate_stock_as_of_pdf(
        _report(), SimpleNamespace(country=country), lang
    )
    return pdf.decode()


@pytest.mark.anyio
async def test_english_sheet_writes_the_ledger_start_like_the_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = await _sheet_html(monkeypatch, 'en')
    assert 'The movement ledger starts on: Sep 30, 2026' in html


@pytest.mark.anyio
async def test_spanish_sheet_calls_the_ledger_what_the_screen_calls_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = await _sheet_html(monkeypatch, 'es')
    assert 'El libro de movimientos empieza el: 30/09/2026' in html
    assert 'registro de movimientos' not in html


@pytest.mark.anyio
async def test_sheet_header_dates_follow_the_language_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    en = await _sheet_html(monkeypatch, 'en')
    assert 'Sep 30, 2026' in en and 'Oct 2, 2026' in en
    assert '2026-09-30' not in en and '2026-10-02' not in en
    pl = await _sheet_html(monkeypatch, 'pl')
    assert '30.09.2026' in pl and '02.10.2026' in pl


@pytest.mark.anyio
async def test_english_sheet_of_an_organization_outside_the_us_is_day_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screen reads 30 Sep 2026 there, so the sheet filed from it must too."""
    uk = await _sheet_html(monkeypatch, 'en', 'GB')
    assert '30 Sep 2026' in uk and '2 Oct 2026' in uk
    assert 'Sep 30, 2026' not in uk
    us = await _sheet_html(monkeypatch, 'en', 'US')
    assert 'Sep 30, 2026' in us
