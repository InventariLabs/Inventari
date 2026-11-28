"""Bulk partner import — XLSX/CSV rows into partners, once per partner.

Every row goes through ``partner_service.create_async``, the door the form
uses. A row is refused, with a reason, when it names a partner the
organization already has: the same name in any letter case, or the same tax
id (compared without spaces and punctuation), whether that partner sits in
the database or a few rows up in the same file.

A country may be written as its code or as its name in English or another
maintained language. A row naming the company it belongs to is a contact
person: it becomes part of that company, not a partner of its own.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any, get_args
from uuid import UUID

import pandas as pd
from babel import Locale
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.contracts._core_dtos import ISO_3166_ALPHA2_CODES
from app.core.import_sheet import (
    RowError,
    cell_text,
    explain,
    read_rows,
    row_get,
)
from app.core.refused_rows import refused_rows_file
from app.i18n._types import Language
from app.i18n.service import get_current_lang, get_error_message
from app.models.partner import Partner
from app.schemas.partner import PartnerAddress, PartnerCreate, PartnerUpdate
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


#: Names other tools write that the locale data spells otherwise.
_COUNTRY_ALIASES = {
    'czech republic': 'CZ',
    'great britain': 'GB',
    'republic of korea': 'KR',
    'russian federation': 'RU',
    'slovak republic': 'SK',
    'turkey': 'TR',
    'united states of america': 'US',
    'viet nam': 'VN',
}


@cache
def _country_codes() -> dict[str, str]:
    """Country code by each name the maintained languages give the country."""
    # "pt" is Brazil's spelling; Portugal's names differ.
    locales = [*get_args(Language), 'pt_PT']
    names = {
        name.casefold(): code
        for locale in locales
        for code, name in Locale.parse(locale).territories.items()
        if code in ISO_3166_ALPHA2_CODES
    }
    return names | _COUNTRY_ALIASES


def _country(text: str | None) -> str | None:
    """A country cell as a code; a word naming no country goes on as written,
    for the address to refuse."""
    if text is None or text.upper() in ISO_3166_ALPHA2_CODES:
        return text
    return _country_codes().get(' '.join(text.casefold().split()), text)


def _name_key(name: str) -> str:
    return ' '.join(name.lower().split())


def _tax_key(tax_id: str) -> str:
    return re.sub(r'[^0-9a-z]', '', tax_id.lower())


@dataclass
class _Known:
    """Who the organization already has, by the two keys a row may repeat."""

    by_name: dict[str, str] = field(default_factory=dict)
    by_tax: dict[str, str] = field(default_factory=dict)
    #: The partner a contact person's row joins when its company is here.
    ids: dict[str, UUID] = field(default_factory=dict)

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
        select(Partner.name, Partner.tax_id, Partner.id)
        .where(Partner.organization_id == org_id)
        .order_by(Partner.created_at)
    )
    for name, tax_id, partner_id in rows.all():
        known.remember(name, tax_id)
        known.ids.setdefault(_name_key(name), partner_id)
    return known


def _build_partner(
    row: pd.Series, mapping: dict[str, Any], default_type: str
) -> PartnerCreate:
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
    address['country'] = _country(address['country'])
    if any(address.values()):
        data['address'] = PartnerAddress(**address)
    return PartnerCreate(**data)


def _company_of(row: pd.Series, mapping: dict[str, Any]) -> str | None:
    """The company a contact person's row belongs to; ``None`` for a partner."""
    company = cell_text(row_get(row, mapping, 'company'))
    name = cell_text(row_get(row, mapping, 'name'))
    if not company or not name or _name_key(company) == _name_key(name):
        return None
    return company


def _contact_rows(
    df: pd.DataFrame, mapping: dict[str, Any]
) -> dict[str, list[tuple[int, str, pd.Series]]]:
    """The contact persons' rows by their company's name key: (index, company, row)."""
    contacts: dict[str, list[tuple[int, str, pd.Series]]] = {}
    for index, row in df.iterrows():
        company = _company_of(row, mapping)
        if company is not None:
            entry = (int(index), company, row)
            contacts.setdefault(_name_key(company), []).append(entry)
    return contacts


def _contact_lines(
    rows: list[tuple[int, str, pd.Series]], mapping: dict[str, Any]
) -> tuple[str, list[str]]:
    """The first contact person's name, and one line per person for the notes."""
    names: list[str] = []
    lines: list[str] = []
    for _, _, row in rows:
        cells = [
            cell_text(row_get(row, mapping, key)) for key in ('name', 'email', 'phone')
        ]
        names.append(cells[0] or '')
        lines.append(', '.join(cell for cell in cells if cell))
    return names[0], lines


def _with_contacts(
    partner_in: PartnerCreate,
    rows: list[tuple[int, str, pd.Series]],
    mapping: dict[str, Any],
) -> PartnerCreate:
    """The company with its contact persons: the first one as its contact
    person, and each one's name, e-mail and phone as a line of its notes."""
    first, lines = _contact_lines(rows, mapping)
    notes = [partner_in.notes] if partner_in.notes else []
    return PartnerCreate.model_validate(
        partner_in.model_dump(exclude_unset=True)
        | {
            'contact_person': partner_in.contact_person or first,
            'notes': '\n'.join([*notes, *lines]),
        }
    )


async def _attach_to_existing(
    db: AsyncSession,
    org_id: UUID,
    partner_id: UUID,
    rows: list[tuple[int, str, pd.Series]],
    mapping: dict[str, Any],
    user: UserContextDTO,
) -> bool:
    """Put the contacts onto the company the organization already has.

    The first contact person fills an empty contact person; every one of them
    becomes a line of the company's notes, the way it does for a company the
    same file adds. ``False`` says the partner is gone, so the caller refuses
    the rows by their company name.
    """
    partner = await partner_service.get_async(db, org_id, partner_id, for_update=True)
    if partner is None:
        return False
    first, lines = _contact_lines(rows, mapping)
    changes: dict[str, Any] = {}
    if not partner.contact_person and first:
        changes['contact_person'] = first
    if lines:
        notes = partner.notes.split('\n') if partner.notes else []
        present = set(notes)
        # A second upload of the same contact export must not write the same
        # person into the notes again.
        added = list(dict.fromkeys(line for line in lines if line not in present))
        if added:
            changes['notes'] = '\n'.join([*notes, *added])
    if changes:
        await partner_service.update_async(
            db, org_id, partner_id, PartnerUpdate(**changes), user_id=user.id
        )
    return True


async def import_partners(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    mapping: dict[str, Any],
    user: UserContextDTO,
    default_type: str = 'SUPPLIER',
) -> dict[str, Any]:
    """Import partners from an XLSX or CSV file based on column mapping."""
    df = read_rows(file_content, filename)
    known = await _preload_known(db, user.organization_id)
    org_id = user.organization_id
    assert org_id is not None

    imported = 0
    folded = 0
    errors: list[dict[str, Any]] = []
    contacts = _contact_rows(df, mapping)
    contact_indexes = {index for rows in contacts.values() for index, _, _ in rows}
    for index, row in df.iterrows():
        if index in contact_indexes:
            continue
        # Data rows from 1, as the preview and every other import number them.
        row_num = int(index) + 1
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
                persons = contacts.get(_name_key(partner_in.name), [])
                if persons:
                    partner_in = _with_contacts(partner_in, persons, mapping)
                await partner_service.create_async(db, org_id, partner_in, user.id)
        except Exception as exc:  # noqa: BLE001 — per-row errors are reported so the batch can continue
            if partner_in is not None:
                known.forget(partner_in.name, partner_in.tax_id)
            errors.append({'row': row_num, 'error': explain(exc, mapping)})
            continue
        imported += 1
        folded += len(contacts.pop(_name_key(partner_in.name), []))

    # What is left belongs to a company this file did not add: it joins the
    # company the organization already has, by the same name key the file
    # matches with, or is refused by its company's name.
    for rows in contacts.values():
        partner_id = known.ids.get(_name_key(rows[0][1]))
        if partner_id is not None:
            try:
                async with db.begin_nested():
                    attached = await _attach_to_existing(
                        db, org_id, partner_id, rows, mapping, user
                    )
            except Exception as exc:  # noqa: BLE001 — per-row errors are reported so the batch can continue
                for index, _, _ in rows:
                    errors.append({'row': index + 1, 'error': explain(exc, mapping)})
                continue
            if attached:
                folded += len(rows)
                continue
        for index, company, _ in rows:
            reason = get_error_message(
                'partner_import_company_missing', get_current_lang(), company=company
            )
            errors.append({'row': index + 1, 'error': reason})

    errors.sort(key=lambda e: e['row'])
    return {
        'total': len(df),
        'imported': imported,
        'contacts': folded,
        'failed': len(errors),
        'errors': errors[:10],
        'refused_file': refused_rows_file(df, errors, filename),
    }
