from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.purchase_orders._service_email import send_po_email


def _make_po(
    *,
    status: str = 'CONFIRMED',
    number: str = 'PO/2026/0001',
    partner_email: str | None = 'test@example.com',
    partner_name: str = 'Acme Corp',
    org_name: str = 'My Org',
) -> MagicMock:
    po = MagicMock()
    po.id = uuid4()
    po.status = status
    po.number = number
    po.partner = MagicMock()
    po.partner.email = partner_email
    po.partner.name = partner_name
    po.organization = MagicMock()
    po.organization.name = org_name
    return po


@pytest.mark.unit
class TestSendPoEmail:
    @pytest.mark.asyncio
    async def test_raises_when_not_found(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='not found'):
            await send_po_email(db, uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_draft(self) -> None:
        db = MagicMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='Cannot send email'):
            await send_po_email(db, po.id, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_no_partner(self) -> None:
        """An order with no supplier is refused for that, not for an address.

        Deleting a partner sets ``partner_id`` to NULL on the completed orders
        that reference it, and "the partner has no email address" then names a
        partner the order no longer has.
        """
        db = MagicMock()
        po = _make_po()
        po.partner = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='no supplier'):
            await send_po_email(db, po.id, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_partner_no_email(self) -> None:
        db = MagicMock()
        po = _make_po(partner_email=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='no email address'):
            await send_po_email(db, po.id, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_invalid_email(self) -> None:
        db = MagicMock()
        po = _make_po(partner_email='not-an-email')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='Invalid partner email'):
            await send_po_email(db, po.id, uuid4())

    @pytest.mark.asyncio
    async def test_escapes_org_name_and_po_number_in_html(self) -> None:
        """org_name and po.number must be HTML-escaped to prevent XSS."""
        po = _make_po(
            number='PO/<script>alert(1)</script>/0001',
            org_name='<img src=x onerror=alert(1)>',
        )
        send_mock = AsyncMock(return_value=True)

        with (
            patch(
                'app.modules.purchase_orders._service_email.get_purchase_order',
                new_callable=AsyncMock,
                return_value=po,
            ),
            patch(
                'app.modules.purchase_orders.po_pdf_service.generate_po_pdf',
                new_callable=AsyncMock,
                return_value=b'PDF',
            ),
            patch(
                'app.core.public_api.core_api',
            ) as mock_core,
        ):
            mock_core.email.send_with_attachment_async = send_mock
            db = MagicMock()
            await send_po_email(db, po.id, uuid4())

        html_content = send_mock.call_args.kwargs['html_content']
        assert '<script>' not in html_content
        assert '&lt;script&gt;' in html_content
        assert '<img' not in html_content
        assert '&lt;img' in html_content

    @pytest.mark.asyncio
    async def test_subject_also_escaped(self) -> None:
        """subject line must also be escaped."""
        po = _make_po(org_name='<b>Bold</b> Corp')
        send_mock = AsyncMock(return_value=True)

        with (
            patch(
                'app.modules.purchase_orders._service_email.get_purchase_order',
                new_callable=AsyncMock,
                return_value=po,
            ),
            patch(
                'app.modules.purchase_orders.po_pdf_service.generate_po_pdf',
                new_callable=AsyncMock,
                return_value=b'PDF',
            ),
            patch(
                'app.core.public_api.core_api',
            ) as mock_core,
        ):
            mock_core.email.send_with_attachment_async = send_mock
            db = MagicMock()
            await send_po_email(db, po.id, uuid4(), lang='en')

        subject = send_mock.call_args.kwargs['subject']
        assert '<b>' not in subject
        assert '&lt;b&gt;' in subject
