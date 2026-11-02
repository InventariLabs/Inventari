"""Bulk partner import — XLSX/CSV rows into partners, once per partner.

Every row goes through ``partner_service.create_async``, the door the form
uses. A row is refused, with a reason, when it names a partner the
organization already has: the same name in any letter case, or the same tax
id (compared without spaces and punctuation), whether that partner sits in
the database or a few rows up in the same file.
"""

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.import_sheet import (
    RowError,
    cell_text,
    explain,
    read_rows,
    row_get,
)
from app.i18n.service import get_current_lang, get_error_message
from app.models.partner import Partner
from app.schemas.partner import PartnerAddress, PartnerCreate
from app.services import partner_service

#: Address columns the sheet may carry; they fold into ``PartnerCreate.address``.
_ADDRESS_FIELDS = ('street', 'city', 'postal_code', 'country')

#: Plain fields copied from the mapped cell as text.
_TEXT_FIELDS = (
    'code',
    'tax_id',
    'email',
    'phone',
    'website',
    'contact_person',
    'notes',
)


def _name_key(name: str) -> str:
    return ' '.join(name.lower().split())


def _tax_key(tax_id: str) -> str:
    return re.sub(r'[^0-9a-z]', '', tax_id.lower())


@dataclass
class _Known:
    """Who the organization already has, by the two keys a row may repeat."""

    by_name: dict[str, str] = field(default_factory=dict)
    by_tax: dict[str, str] = field(default_factory=dict)

    def remember(self, name: str, tax_id: str | None) -> None:
        self.by_name[_name_key(name)] = name
        if tax_id and _tax_key(tax_id):
            self.by_tax[_tax_key(tax_id)] = name

    def forget(self, name: str, tax_id: str | None) -> None:
        self.by_name.pop(_name_key(name), None)
        if tax_id:
            self.by_tax.pop(_tax_key(tax_id), None)

    def match(self, name: str, tax_id: str | None) -> str | None:
        """The name of the partner this row repeats, if any."""
        found = self.by_name.get(_name_key(name))
        if found is None and tax_id and _tax_key(tax_id):
            found = self.by_tax.get(_tax_key(tax_id))
        return found


async def _preload_known(db: AsyncSession, org_id: UUID | None) -> _Known:
    known = _Known()
    rows = await db.execute(
        select(Partner.name, Partner.tax_id).where(Partner.organization_id == org_id)
    )
    for name, tax_id in rows.all():
        known.remember(name, tax_id)
    return known


def _build_partner(row: pd.Series, mapping: dict, default_type: str) -> PartnerCreate:
    """One row as the create endpoint would have received it."""
    name = cell_text(row_get(row, mapping, 'name'))
    if not name:
        raise RowError(
            get_error_message('partner_import_name_missing', get_current_lang())
        )
    data: dict[str, Any] = {
        'name': name,
        'type': cell_text(row_get(row, mapping, 'type')) or default_type,
    }
    for key in _TEXT_FIELDS:
        data[key] = cell_text(row_get(row, mapping, key))
    address = {key: cell_text(row_get(row, mapping, key)) for key in _ADDRESS_FIELDS}
    if any(address.values()):
        data['address'] = PartnerAddress(**address)
    return PartnerCreate(**data)


async def import_partners(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    mapping: dict,
    user: UserContextDTO,
    default_type: str = 'SUPPLIER',
) -> dict:
    """Import partners from an XLSX or CSV file based on column mapping."""
    df = read_rows(file_content, filename)
    known = await _preload_known(db, user.organization_id)
    org_id = user.organization_id
    assert org_id is not None

    imported = 0
    errors: list[dict] = []
    for index, row in df.iterrows():
        row_num = int(index) + 2  # header row + 1-based numbering
        partner_in: PartnerCreate | None = None
        try:
            async with db.begin_nested():
                partner_in = _build_partner(row, mapping, default_type)
                twin = known.match(partner_in.name, partner_in.tax_id)
                if twin is not None:
                    raise RowError(
                        get_error_message(
                            'partner_import_duplicate',
                            get_current_lang(),
                            twin=twin,
                        )
                    )
                known.remember(partner_in.name, partner_in.tax_id)
                await partner_service.create_async(db, org_id, partner_in, user.id)
        except Exception as exc:  # noqa: BLE001 — per-row errors are reported so the batch can continue
            if partner_in is not None:
                known.forget(partner_in.name, partner_in.tax_id)
            errors.append({'row': row_num, 'error': explain(exc, mapping)})
            continue
        imported += 1

    return {
        'total': len(df),
        'imported': imported,
        'failed': len(errors),
        'errors': errors[:10],
    }
