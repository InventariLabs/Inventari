"""The two papers a hand-over needs: what to prepare, and what went out.

Both print through the shared template engine and PDF service, so paper size,
issuer block and the sandbox are the ones every other printout uses. An
organization may store its own layout as a ``PICK_LIST`` or ``HANDOVER``
document template for this module; the built-in one prints when it has none.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import format_date_for, format_datetime_for, get_logger
from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from .models import RentalBooking

logger = get_logger(__name__)

DOCUMENT_PICK_LIST = 'PICK_LIST'
DOCUMENT_HANDOVER = 'HANDOVER'

LABELS: dict[str, dict[str, str]] = {
    'en': {
        'pick_title': 'Pick list',
        'handover_title': 'Hand-over sheet',
        'booking': 'Booking',
        'borrower': 'Borrower',
        'window': 'Booked window',
        'from': 'From',
        'to': 'Until',
        'lines': 'To prepare',
        'handed_lines': 'Handed out',
        'item': 'Item',
        'model': 'Model',
        'quantity': 'Qty',
        'kit': 'Kit',
        'serial': 'Serial number',
        'condition': 'Condition',
        'handed_out': 'Handed out at',
        'note': 'Note',
        'signature': 'Signature of the borrower',
        'issued_by': 'Handed out by',
        'footer': 'This document was generated from Inventari.',
        'GOOD': 'Working',
        'DAMAGED': 'Damaged but working',
        'NEEDS_REPAIR': 'Needs service',
    },
    'pl': {
        'pick_title': 'Lista do spakowania',
        'handover_title': 'Protokół wydania',
        'booking': 'Rezerwacja',
        'borrower': 'Biorący',
        'window': 'Okno rezerwacji',
        'from': 'Od',
        'to': 'Do',
        'lines': 'Do przygotowania',
        'handed_lines': 'Wydane',
        'item': 'Zasób',
        'model': 'Model',
        'quantity': 'Ilość',
        'kit': 'Zestaw',
        'serial': 'Numer seryjny',
        'condition': 'Stan',
        'handed_out': 'Wydano o',
        'note': 'Uwagi',
        'signature': 'Podpis biorącego',
        'issued_by': 'Wydał',
        'footer': 'Dokument wygenerowany z systemu Inventari.',
        'GOOD': 'Sprawny',
        'DAMAGED': 'Uszkodzony, ale działający',
        'NEEDS_REPAIR': 'Do serwisu',
    },
    'de': {
        'pick_title': 'Packliste',
        'handover_title': 'Übergabeprotokoll',
        'booking': 'Buchung',
        'borrower': 'Ausleihende Person',
        'window': 'Buchungszeitraum',
        'from': 'Von',
        'to': 'Bis',
        'lines': 'Vorzubereiten',
        'handed_lines': 'Ausgegeben',
        'item': 'Gegenstand',
        'model': 'Modell',
        'quantity': 'Menge',
        'kit': 'Set',
        'serial': 'Seriennummer',
        'condition': 'Zustand',
        'handed_out': 'Ausgegeben am',
        'note': 'Notiz',
        'signature': 'Unterschrift der ausleihenden Person',
        'issued_by': 'Ausgegeben von',
        'footer': 'Dieses Dokument wurde mit Inventari erstellt.',
        'GOOD': 'Funktionsfähig',
        'DAMAGED': 'Beschädigt, aber funktionsfähig',
        'NEEDS_REPAIR': 'Reparaturbedarf',
    },
    'fr': {
        'pick_title': 'Liste de préparation',
        'handover_title': 'Fiche de remise',
        'booking': 'Réservation',
        'borrower': 'Emprunteur',
        'window': 'Période réservée',
        'from': 'Du',
        'to': "Jusqu'au",
        'lines': 'À préparer',
        'handed_lines': 'Remis',
        'item': 'Équipement',
        'model': 'Modèle',
        'quantity': 'Qté',
        'kit': 'Kit',
        'serial': 'Numéro de série',
        'condition': 'État',
        'handed_out': 'Remis le',
        'note': 'Remarque',
        'signature': "Signature de l'emprunteur",
        'issued_by': 'Remis par',
        'footer': 'Document généré depuis Inventari.',
        'GOOD': 'Fonctionnel',
        'DAMAGED': 'Endommagé mais fonctionnel',
        'NEEDS_REPAIR': 'À réparer',
    },
    'es': {
        'pick_title': 'Lista de preparación',
        'handover_title': 'Hoja de entrega',
        'booking': 'Reserva',
        'borrower': 'Prestatario',
        'window': 'Periodo reservado',
        'from': 'Desde',
        'to': 'Hasta',
        'lines': 'Por preparar',
        'handed_lines': 'Entregado',
        'item': 'Activo',
        'model': 'Modelo',
        'quantity': 'Cant.',
        'kit': 'Kit',
        'serial': 'Número de serie',
        'condition': 'Estado',
        'handed_out': 'Entregado el',
        'note': 'Nota',
        'signature': 'Firma del prestatario',
        'issued_by': 'Entregado por',
        'footer': 'Documento generado desde Inventari.',
        'GOOD': 'Funciona',
        'DAMAGED': 'Dañado pero funciona',
        'NEEDS_REPAIR': 'Necesita reparación',
    },
    'pt': {
        'pick_title': 'Lista de preparação',
        'handover_title': 'Folha de entrega',
        'booking': 'Reserva',
        'borrower': 'Requerente',
        'window': 'Período reservado',
        'from': 'De',
        'to': 'Até',
        'lines': 'A preparar',
        'handed_lines': 'Entregue',
        'item': 'Equipamento',
        'model': 'Modelo',
        'quantity': 'Qtd.',
        'kit': 'Conjunto',
        'serial': 'Número de série',
        'condition': 'Estado',
        'handed_out': 'Entregue a',
        'note': 'Nota',
        'signature': 'Assinatura do requerente',
        'issued_by': 'Entregue por',
        'footer': 'Documento gerado a partir do Inventari.',
        'GOOD': 'A funcionar',
        'DAMAGED': 'Danificado mas a funcionar',
        'NEEDS_REPAIR': 'Precisa de reparação',
    },
}

DEFAULT_LANG = 'en'


def labels_for(lang: str) -> dict[str, str]:
    return LABELS.get(lang, LABELS[DEFAULT_LANG])


_STYLE = """
  @page { margin: 1.8cm; }
  body { font-family: sans-serif; font-size: 11pt; color: #1a1a1a; line-height: 1.45; }
  h1 { font-size: 18pt; text-align: center; margin: 0 0 0.2cm; }
  .subtitle { text-align: center; color: #555; font-size: 10pt; margin-bottom: 0.8cm; }
  h2 { font-size: 12pt; margin: 0.7cm 0 0.2cm; border-bottom: 2px solid #333; padding-bottom: 3px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 0.4cm; }
  th, td { border: 1px solid #ccc; padding: 6px 9px; text-align: left; font-size: 10pt; }
  th { background: #f4f4f4; font-weight: 600; }
  .facts th { width: 30%; }
  .footer { text-align: center; font-size: 8pt; color: #999; margin-top: 1.2cm; border-top: 1px solid #eee; padding-top: 4px; }
  .sign { margin-top: 2cm; display: flex; justify-content: space-between; }
  .sign div { width: 45%; border-top: 1px solid #333; padding-top: 4px; font-size: 9pt; color: #555; text-align: center; }
  .kit-name { color: #555; font-size: 9pt; }
"""

_PICK_LIST_HTML = """\
<!DOCTYPE html>
<html lang="{{lang}}">
<head><meta charset="utf-8"><style>{{style}}</style></head>
<body>
  <h1>{{L.pick_title}}</h1>
  <div class="subtitle">{{issuer.name}} &mdash; {{booking_ref}}</div>
  <table class="facts">
    <tr><th>{{L.borrower}}</th><td>{{borrower_name}}</td></tr>
    <tr><th>{{L.window}}</th><td>{{L.from}} {{starts_at}} &middot; {{L.to}} {{ends_at}}</td></tr>
    {% if note %}<tr><th>{{L.note}}</th><td>{{note}}</td></tr>{% endif %}
  </table>
  <h2>{{L.lines}}</h2>
  <table>
    <thead><tr>
      <th>{{L.item}}</th><th>{{L.model}}</th><th>{{L.quantity}}</th><th>{{L.serial}}</th>
    </tr></thead>
    <tbody>
    {% for row in rows %}
      <tr>
        <td>{{row.name}}{% if row.kit_name %}<div class="kit-name">{{L.kit}}: {{row.kit_name}}</div>{% endif %}</td>
        <td>{{row.model or ''}}</td>
        <td>{{row.quantity}}</td>
        <td>{{row.serials}}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="footer">{{L.footer}} &mdash; {{printed_at}}</div>
</body>
</html>
"""

_HANDOVER_HTML = """\
<!DOCTYPE html>
<html lang="{{lang}}">
<head><meta charset="utf-8"><style>{{style}}</style></head>
<body>
  <h1>{{L.handover_title}}</h1>
  <div class="subtitle">{{issuer.name}} &mdash; {{booking_ref}}</div>
  <table class="facts">
    <tr><th>{{L.borrower}}</th><td>{{borrower_name}}</td></tr>
    <tr><th>{{L.window}}</th><td>{{L.from}} {{starts_at}} &middot; {{L.to}} {{ends_at}}</td></tr>
    <tr><th>{{L.handed_out}}</th><td>{{handed_out_at}}</td></tr>
    {% if note %}<tr><th>{{L.note}}</th><td>{{note}}</td></tr>{% endif %}
  </table>
  <h2>{{L.handed_lines}}</h2>
  <table>
    <thead><tr>
      <th>{{L.item}}</th><th>{{L.model}}</th><th>{{L.serial}}</th><th>{{L.condition}}</th>
    </tr></thead>
    <tbody>
    {% for row in rows %}
      <tr>
        <td>{{row.name}}{% if row.kit_name %}<div class="kit-name">{{L.kit}}: {{row.kit_name}}</div>{% endif %}</td>
        <td>{{row.model or ''}}</td>
        <td>{{row.serials}}</td>
        <td>{{row.condition}}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="sign">
    <div>{{L.issued_by}}</div>
    <div>{{L.signature}}</div>
  </div>
  <div class="footer">{{L.footer}} &mdash; {{printed_at}}</div>
</body>
</html>
"""


def _booking_ref(booking: RentalBooking) -> str:
    return f'{booking.starts_at.year}/{str(booking.id)[:8].upper()}'


async def _assets(db: AsyncSession, org_id: UUID) -> dict[UUID, EquipmentAssetDTO]:
    assets = await equipment_api.list_bookable_assets_async(
        db, org_id, include_retired=True
    )
    return {asset.id: asset for asset in assets}


def _rows(
    booking: RentalBooking,
    assets: dict[UUID, EquipmentAssetDTO],
    labels: dict[str, str],
    *,
    handover: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in booking.lines:
        if handover:
            for unit in line.units:
                asset = assets.get(unit.item_id)
                rows.append(
                    {
                        'name': asset.name if asset is not None else '',
                        'model': asset.model if asset is not None else None,
                        'quantity': 1,
                        'serials': (
                            (asset.serial_number or asset.asset_tag or '')
                            if asset is not None
                            else ''
                        ),
                        'condition': labels.get(unit.condition or '', ''),
                        'kit_name': line.kit_name,
                    }
                )
            continue
        rows.append(
            {
                'name': (
                    assets[line.item_id].name
                    if line.item_id is not None and line.item_id in assets
                    else (line.model or '')
                ),
                'model': (
                    assets[line.item_id].model
                    if line.item_id is not None and line.item_id in assets
                    else line.model
                ),
                'quantity': line.quantity,
                'serials': (
                    assets[line.item_id].serial_number or ''
                    if line.item_id is not None and line.item_id in assets
                    else ''
                ),
                'condition': '',
                'kit_name': line.kit_name,
            }
        )
    return rows


async def _stored_layout(
    db: AsyncSession, org_id: UUID, document_type: str
) -> str | None:
    template = await core_api.templates.get_default_async(
        db, org_id, 'rentals', document_type
    )
    return template.body_html if template is not None else None


async def render_document_html(
    db: AsyncSession,
    org_id: UUID,
    booking: RentalBooking,
    document_type: str,
    lang: str = DEFAULT_LANG,
) -> str:
    labels = labels_for(lang)
    tz = await core_api.organizations.timezone_async(db, org_id)
    issuer = await core_api.pdf.issuer_async(db, org_id, lang)
    assets = await _assets(db, org_id)
    handover = document_type == DOCUMENT_HANDOVER
    starts = booking.starts_at.astimezone(tz)
    ends = booking.ends_at.astimezone(tz)
    context: dict[str, Any] = {
        'lang': lang,
        'style': _STYLE,
        'L': labels,
        'issuer': issuer,
        'booking_ref': _booking_ref(booking),
        'borrower_name': booking.borrower_name,
        'starts_at': format_datetime_for(lang, starts),
        'ends_at': format_datetime_for(lang, ends),
        'handed_out_at': format_datetime_for(
            lang, booking.picked_up_at.astimezone(tz) if booking.picked_up_at else None
        ),
        'note': booking.note or '',
        'rows': _rows(booking, assets, labels, handover=handover),
        'printed_at': format_date_for(lang, datetime.now(tz).date()),
    }
    stored = await _stored_layout(db, org_id, document_type)
    if stored:
        try:
            return core_api.pdf.render_html(stored, context)
        except Exception:
            # A broken layout must not kill the print.
            logger.warning(
                '[rentals] the stored %s layout of %s did not render',
                document_type,
                org_id,
                exc_info=True,
            )
    return core_api.pdf.render_html(
        _HANDOVER_HTML if handover else _PICK_LIST_HTML, context
    )


async def render_document_pdf(
    db: AsyncSession,
    org_id: UUID,
    booking: RentalBooking,
    document_type: str,
    lang: str = DEFAULT_LANG,
) -> bytes:
    html = await render_document_html(db, org_id, booking, document_type, lang)
    return await core_api.pdf.render_document_pdf_async(db, org_id, html)
