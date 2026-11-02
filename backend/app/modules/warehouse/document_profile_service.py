"""Document profile presets, reads and the country's legal answers.

A profile carries two axes at once. A preset supplies the shape — how the
organization works: numbering, type labels, visible line fields, print
template, value tracking. The country supplies the law — the rate its
documents apply and whether a partner must carry a tax id (see
``country_tax_rules``). The profile row holds an explicit entry only when
somebody made one; where it says ``None``, the organization answers, the
same way ``default_currency`` defers to the organization currency.
"""

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import await_if_awaitable
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from .country_tax_rules import get_country_rule
from .document_validation_service import validate_location_async
from .models import DocumentProfile, TaxHandling
from .models.profile import DEFAULT_NUMBER_PADDING, DEFAULT_NUMBERING_FORMAT
from .schemas import DocumentProfileUpdate

PRESETS: dict[str, dict[str, Any]] = {
    'Simple': {
        'value_tracking_enabled': False,
        'tax_handling': TaxHandling.NONE.value,
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': DEFAULT_NUMBERING_FORMAT,
        'number_padding': DEFAULT_NUMBER_PADDING,
        'type_labels': None,
        'default_unit': 'pcs',
        'visible_line_fields': [],
        'print_template': 'auto',
        'default_currency': None,
    },
    'PL Magazyn': {
        'value_tracking_enabled': True,
        'tax_handling': TaxHandling.PER_LINE_RATE.value,
        # no pinned rate — see the currency note at the bottom of this
        # preset: a preset is a way of working, not a country, and a rate
        # enters the net/tax/gross arithmetic rather than labelling it.
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE_LABEL}/{YEAR}/{MONTH}/{SEQ:04d}',
        'number_padding': 4,
        'type_labels': {
            'IN': 'PZ',
            'OUT': 'WZ',
            'INT': 'MM',
            'INTERNAL_IN': 'PW',
            'INTERNAL_OUT': 'RW',
            'CORRECTION': 'KOR',
            # The seven types the interface offers share one shape: the
            # Polish paperwork code, which the label shows in brackets and
            # the numbering prefix writes. Scrap had a label and no code —
            # "Złomowanie" alone, beside six bracketed siblings.
            'SCRAP': 'ZL',
        },
        'default_unit': 'pcs',
        'visible_line_fields': ['batch_number', 'expiry_date'],
        'print_template': 'pl_pz',
        # no pinned currency — regional presets must not override the
        # organization currency the way EUR/PLN/GBP used to.
        'default_currency': None,
    },
    'UK Warehouse': {
        'value_tracking_enabled': False,
        'tax_handling': TaxHandling.NONE.value,
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE_LABEL}/{YEAR}/{SEQ:04d}',
        'number_padding': 4,
        'type_labels': {
            'IN': 'GRN',
            'OUT': 'DN',
            'INT': 'ST',
            'INTERNAL_IN': 'IPR',
            'INTERNAL_OUT': 'IC',
            'CORRECTION': 'CORR',
        },
        'default_unit': 'pcs',
        'visible_line_fields': [],
        'print_template': 'auto',
        # see the PL Magazyn note — the organization currency wins.
        'default_currency': None,
    },
    # The three national presets are not the same kind of thing, on purpose.
    # ``PL Magazyn`` tracks values and a per-line VAT rate because a Polish
    # warehouse document (PZ, WZ) is a book-keeping record: it carries the
    # goods' value into the accounts. ``UK Warehouse`` and ``DE Lager`` do
    # not: a goods-received note or a Lieferschein is a delivery note, it
    # states what moved and carries no amount or tax. So ``DE Lager`` is a
    # delivery note without tax — ``value_tracking_enabled`` False,
    # ``tax_handling`` NONE — and it does not ask for the partner's tax id
    # either: the USt-IdNr. is an invoice matter, and a document with no tax
    # field would refuse a confirm for a number it never prints. An
    # organization that wants the check turns it on in its profile (see
    # ``country_tax_rules``).
    'DE Lager': {
        'value_tracking_enabled': False,
        'tax_handling': TaxHandling.NONE.value,
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE_LABEL}/{YEAR}/{SEQ:04d}',
        'number_padding': 4,
        'type_labels': {
            'IN': 'WE',
            'OUT': 'WA',
            'INT': 'UML',
            'INTERNAL_IN': 'IE',
            'INTERNAL_OUT': 'IV',
            'CORRECTION': 'KORR',
        },
        'default_unit': 'pcs',
        'visible_line_fields': ['batch_number'],
        'print_template': 'auto',
        'default_currency': None,
    },
    # France and Spain, like the three above, carry the local paperwork
    # vocabulary and no law: the rate and the tax-id requirement are the
    # country's (``country_tax_rules``). The codes follow common practice:
    # bon de réception / bon de livraison / bon de transfert, and albarán de
    # entrada / de salida / traspaso. The ``auto`` print layout writes both
    # in the print language, like ``UK Warehouse`` and ``DE Lager``.
    'FR Entrepôt': {
        'value_tracking_enabled': False,
        'tax_handling': TaxHandling.NONE.value,
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE_LABEL}/{YEAR}/{SEQ:04d}',
        'number_padding': 4,
        'type_labels': {
            'IN': 'BR',
            'OUT': 'BL',
            'INT': 'BT',
            'INTERNAL_IN': 'ERI',
            'INTERNAL_OUT': 'SCI',
            'CORRECTION': 'COR',
        },
        'default_unit': 'pcs',
        'visible_line_fields': ['batch_number', 'expiry_date'],
        'print_template': 'auto',
        'default_currency': None,
    },
    'ES Almacén': {
        'value_tracking_enabled': False,
        'tax_handling': TaxHandling.NONE.value,
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE_LABEL}/{YEAR}/{SEQ:04d}',
        'number_padding': 4,
        'type_labels': {
            'IN': 'AE',
            'OUT': 'AS',
            'INT': 'TR',
            'INTERNAL_IN': 'EI',
            'INTERNAL_OUT': 'SI',
            'CORRECTION': 'COR',
        },
        'default_unit': 'pcs',
        'visible_line_fields': ['batch_number', 'expiry_date'],
        'print_template': 'auto',
        'default_currency': None,
    },
    'Full Value': {
        'value_tracking_enabled': True,
        'tax_handling': TaxHandling.SIMPLE_RATE.value,
        # no pinned rate — this preset ships with the equipment_wms
        # profile, which is a way of working, not a country: the 20% that
        # used to sit here was the UK basic rate, silently applied to
        # organizations in every other one. An untaxed document is worth
        # its net, so an empty rate costs the profile nothing.
        'default_tax_rate': None,
        'require_partner_tax_id': None,
        'numbering_format': '{TYPE}/{YEAR}/{SEQ:03d}',
        'number_padding': 3,
        'type_labels': None,
        'default_unit': 'pcs',
        'visible_line_fields': [],
        'print_template': 'auto',
        'default_currency': None,
    },
}


async def get_profile(db: Any, org_id: UUID) -> DocumentProfile | None:
    result = await await_if_awaitable(
        db.execute(
            select(DocumentProfile).where(DocumentProfile.organization_id == org_id)
        )
    )
    return cast(DocumentProfile | None, result.scalars().first())


async def create_default_profile(db: Any, org_id: UUID) -> DocumentProfile:
    profile = DocumentProfile(
        organization_id=org_id,
        name='Simple',
        **PRESETS['Simple'],
    )
    db.add(profile)
    await await_if_awaitable(db.flush())
    await await_if_awaitable(db.refresh(profile))
    return profile


async def get_or_create_profile(db: Any, org_id: UUID) -> DocumentProfile:
    profile = await get_profile(db, org_id)
    if not profile:
        profile = await create_default_profile(db, org_id)
    return profile


async def name_quarantine_shelf(
    db: Any, org_id: UUID, location_id: UUID
) -> DocumentProfile:
    """Take *location_id* as the profile's quarantine shelf, if it names none.

    Onboarding calls this with the shelf the product profile seeds under
    ``QUARANTINE_LOCATION_CODE``, so a fresh organization can receive a
    damaged unit and finish the receipt without an administrator opening the
    document settings first. Without a name the receipt is refused at
    completion — after the receiving session has recorded everything, and in
    front of whoever on the floor may not open those settings.

    A shelf somebody already named stays: the answer is theirs to change,
    here or in the document settings section. The caller owns the
    transaction — this writes nothing the caller's commit does not settle.
    """
    profile = await get_or_create_profile(db, org_id)
    if profile.quarantine_location_id is None:
        profile.quarantine_location_id = location_id
    return profile


async def resolve_document_currency(
    db: AsyncSession, org_id: UUID, profile: DocumentProfile
) -> str | None:
    """documents follow the organization currency.

    The profile's ``default_currency`` is only an explicit override. When it
    is empty, the organization's currency is the source of truth — presets no
    longer hardcode EUR (or any other currency) over the organization.
    """
    if profile.default_currency:
        return profile.default_currency
    org = await core_api.organizations.get_async(db, org_id)
    return org.currency if org else None


async def resolve_document_tax_rate(
    db: AsyncSession, org_id: UUID, profile: DocumentProfile
) -> Decimal | None:
    """The rate the organization's documents apply.

    Mirrors ``resolve_document_currency``: the profile's ``default_tax_rate``
    is only an explicit override. When it is empty the country's standard
    rate stands, so a Polish organization on a warehouse profile applies 23%
    without a visit to Settings. A country with no row leaves the rate empty
    — an untaxed document is worth its net.
    """
    if profile.default_tax_rate is not None:
        return profile.default_tax_rate
    org = await core_api.organizations.get_async(db, org_id)
    rule = get_country_rule(org.country if org else None)
    return rule.default_tax_rate if rule else None


async def resolve_partner_tax_id_required(
    db: AsyncSession, org_id: UUID, profile: DocumentProfile
) -> bool:
    """Whether the organization's documents demand a partner's tax id.

    The profile field is tri-state: ``None`` is "no opinion", while True or
    False is an explicit entry and wins over the country. With no opinion
    the country answers — and a country with no row (or no country at all)
    requires nothing, so an installation that never set one behaves as it
    did before the country was read.
    """
    if profile.require_partner_tax_id is not None:
        return profile.require_partner_tax_id
    org = await core_api.organizations.get_async(db, org_id)
    rule = get_country_rule(org.country if org else None)
    return rule.require_partner_tax_id if rule else False


async def apply_preset(db: Any, org_id: UUID, preset_name: str) -> DocumentProfile:
    if preset_name not in PRESETS:
        raise ServiceRejectionError(
            'document_preset_unknown',
            name=preset_name,
            available=', '.join(PRESETS),
        )

    profile = await get_profile(db, org_id)
    if not profile:
        profile = DocumentProfile(organization_id=org_id)
        db.add(profile)

    preset = PRESETS[preset_name]
    profile.name = preset_name
    profile.value_tracking_enabled = preset['value_tracking_enabled']
    profile.tax_handling = preset['tax_handling']
    profile.default_tax_rate = preset['default_tax_rate']
    profile.require_partner_tax_id = preset['require_partner_tax_id']
    profile.numbering_format = preset['numbering_format']
    profile.number_padding = preset.get('number_padding', DEFAULT_NUMBER_PADDING)
    profile.type_labels = preset['type_labels']
    profile.default_unit = preset['default_unit']
    profile.visible_line_fields = preset['visible_line_fields']
    profile.print_template = preset['print_template']
    profile.default_currency = preset.get('default_currency')

    await await_if_awaitable(db.flush())
    await await_if_awaitable(db.refresh(profile))
    return profile


async def apply_country_preset(
    db: Any, org_id: UUID, country: str | None
) -> DocumentProfile | None:
    """Apply the preset of the organization's country, keeping the profile's
    choice of value tracking and tax handling.

    Onboarding offers the country's paperwork (document names, numbering,
    print layout) on top of the working style the product profile picked.
    Several country presets switch value tracking off and set their own tax
    mode, which would silently undo a profile that turned value tracking on
    and keep the country's standard rate off the first document. Those
    settings are carried over from what is already stored (value tracking
    off, as on a fresh profile, when nothing is).
    Returns ``None`` when the country has no preset.
    """
    rule = get_country_rule(country)
    if rule is None or rule.document_preset is None:
        return None
    existing = await get_profile(db, org_id)
    # `existing` is the row apply_preset overwrites, so read it first.
    kept = (
        (
            existing.value_tracking_enabled,
            existing.tax_handling,
            existing.default_tax_rate,
        )
        if existing
        else None
    )
    profile = await apply_preset(db, org_id, rule.document_preset)
    if kept:
        (
            profile.value_tracking_enabled,
            profile.tax_handling,
            profile.default_tax_rate,
        ) = kept
    else:
        profile.value_tracking_enabled = False
    return profile


_PRESETTABLE_FIELDS = {
    'name',
    'value_tracking_enabled',
    'tax_handling',
    'default_tax_rate',
    'require_partner_tax_id',
    'require_unit_price',
    'confirm_shelf_by_scan',
    'numbering_format',
    'number_padding',
    'type_labels',
    'default_unit',
    'visible_line_fields',
    'print_template',
    'default_template_id',
    'default_currency',
    'quarantine_location_id',
    'approval_threshold',
    'approval_required_for_types',
    'pick_order_strategy',
    'tracking_url_templates',
}


async def update_profile(
    db: Any,
    org_id: UUID,
    data: DocumentProfileUpdate,
) -> DocumentProfile:
    profile = await get_or_create_profile(db, org_id)

    provided_fields = data.model_fields_set & _PRESETTABLE_FIELDS

    # The shelf is a place goods will be booked onto, so it has to be one:
    # the same question every other destination a person names is asked.
    if data.quarantine_location_id is not None:
        await validate_location_async(
            db,
            org_id,
            data.quarantine_location_id,
            internal_only=True,
            active_only=True,
        )

    for field in provided_fields:
        setattr(profile, field, getattr(data, field))

    await await_if_awaitable(db.flush())
    await await_if_awaitable(db.refresh(profile))
    return profile
