import html
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger

from ._service_crud import get_purchase_order

logger = get_logger(__name__)


async def send_po_email(
    db: AsyncSession, po_id: UUID, org_id: UUID, lang: str = 'en'
) -> bool:
    from app.core.public_api import core_api
    from app.modules.purchase_orders.po_pdf_service import generate_po_pdf

    po = await get_purchase_order(db, org_id, po_id)
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')

    if po.status not in {'CONFIRMED', 'COMPLETED'}:
        raise ServiceRejectionError('po_email_invalid_status', status=po.status)

    # Two different refusals used to share one sentence. A confirmed order
    # always named a supplier, but deleting that partner sets `partner_id` to
    # NULL on the completed orders that reference it — and "the partner has no
    # email address" then sends the reader looking at an address book for a
    # partner that is not there any more.
    partner = po.partner
    if not partner:
        raise ServiceRejectionError('po_has_no_partner')
    if not partner.email:
        raise ServiceRejectionError('partner_has_no_email')
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', partner.email):
        raise ServiceRejectionError('po_email_invalid_address', email=partner.email)

    org_name = po.organization.name if po.organization else 'Unknown'
    safe_org = html.escape(org_name)
    safe_number = html.escape(po.number)
    pdf_bytes = await generate_po_pdf(po, lang=lang, db=db, org_id=org_id)

    content = {
        'pl': {
            'subject': f'Zamówienie {safe_number} od {safe_org}',
            'body': f'W załączniku przesyłamy zamówienie zakupowe <b>{safe_number}</b> od firmy {safe_org}.',
            'footer': 'Wiadomość wygenerowana automatycznie przez system Inventari.',
        },
        'en': {
            'subject': f'Purchase Order {safe_number} from {safe_org}',
            'body': f'Please find attached Purchase Order <b>{safe_number}</b> from {safe_org}.',
            'footer': 'This is an automatically generated message from Inventari.',
        },
        'de': {
            'subject': f'Bestellung {safe_number} von {safe_org}',
            'body': f'Anbei senden wir Ihnen die Bestellung <b>{safe_number}</b> von {safe_org}.',
            'footer': 'Diese Nachricht wurde automatisch von Inventari erstellt.',
        },
        'fr': {
            'subject': f'Commande {safe_number} de {safe_org}',
            'body': f'Veuillez trouver ci-joint la commande <b>{safe_number}</b> de {safe_org}.',
            'footer': 'Ce message a été généré automatiquement par Inventari.',
        },
        'es': {
            'subject': f'Pedido {safe_number} de {safe_org}',
            'body': f'Adjunto encontrará el pedido <b>{safe_number}</b> de {safe_org}.',
            'footer': 'Este mensaje ha sido generado automáticamente por Inventari.',
        },
    }

    t = content.get(lang, content['en'])

    html_content = f"""
    <html>
        <body style="font-family: sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2563eb;">{t['body']}</h2>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #999;">{t['footer']}</p>
            </div>
        </body>
    </html>
    """

    return await core_api.email.send_with_attachment_async(
        to_email=partner.email,
        subject=t['subject'],
        html_content=html_content,
        attachment_bytes=pdf_bytes,
        attachment_filename=f'{safe_number}.pdf',
        organization_id=org_id,
    )
