"""
Base seed profile — neutral, vertical-agnostic defaults.

Contains:
  - Units of Measure (weight, volume, unit, length)
  - Neutral storage types: SHELF, STORAGE_ROOM, SYSTEM

These are safe defaults for every vertical. No food, equipment,
or domain-specific assumptions.
"""

from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)


class _StorageTypeRequired(TypedDict):
    name: str
    type_code: str
    behavior_mode: str


class _StorageTypeData(_StorageTypeRequired, total=False):
    icon: str
    is_system: bool
    default_settings: dict
    context_schema: list
    #: The declared name per language, keyed by language code, e.g.
    #: ``{'pl': {'name': 'Zamrażarka'}}``. Same contract as a module
    #: declaration's ``translations``: the seeder writes the entry for the
    #: language it is seeding in, and falls back to ``name`` above for a
    #: language that declares none. A type's name is data — it stands in the
    #: storage picker, on the storage's card and in every exported row — so
    #: it is written once in the reader's language, exactly as a location's
    #: name is.
    translations: dict[str, dict[str, str]]


def seed_uom(
    db: Session,
    *,
    units: list[dict] | None = None,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Add standard Units of Measure (neutral, shared across all verticals).

    Args:
        db: Active SQLAlchemy session.
        units: Catalogue to seed; defaults to the neutral ``UOM_UNITS``.
            The food profile passes its kitchen measures here so the neutral
            base stays free of one vertical's vocabulary.
        insert_only: When True, existing records are left untouched; only
            missing rows are inserted. Used by profile switching to avoid
            overwriting user customisations.
        commit: When True (default), commits the transaction at the end.
            Pass False to keep the seeder inside a larger transaction
            owned by the caller (e.g. a profile switch service).
    """
    from app.models.uom import Uom, UomCategory

    from ._uom_data import UOM_CATEGORIES, UOM_UNITS

    if units is None:
        units = UOM_UNITS

    cat_map = {}
    for c_data in UOM_CATEGORIES:
        cat = db.scalars(
            select(UomCategory).where(UomCategory.name == c_data['name'])
        ).first()
        if not cat:
            cat = UomCategory(**c_data)
            db.add(cat)
            db.flush()
        cat_map[cat.name] = cat.id

    for u_data in units:
        row = {k: v for k, v in u_data.items() if k != 'category'}
        cat_id = cat_map.get(str(u_data['category']))
        if not cat_id:
            continue
        existing = db.scalars(select(Uom).where(Uom.name == row['name'])).first()
        if not existing:
            db.add(Uom(**row, category_id=cat_id, is_system=True))
        elif not insert_only:
            # Rounding is the one property a run may correct on an existing
            # row: a unit seeded before this catalogue carried it took the
            # column default of 0.01, so a piece could be recorded in
            # hundredths. Names, factors and symbols stay as the
            # organization has them.
            existing.rounding = Decimal(str(row['rounding']))

    if commit:
        try:
            db.commit()
            logger.info('[base] Added %d units of measure', len(units))
        except SQLAlchemyError:
            db.rollback()
            raise
    else:
        db.flush()


def upsert_storage_types(
    db: Session,
    storage_types: list[_StorageTypeData],
    *,
    organization_id: UUID,
    insert_only: bool = False,
) -> None:
    """Insert or refresh *storage_types* owned by *organization_id*.

       Every profile's storage-type seed goes through here, so the owner is not
       something a seeder can forget: rows without one are read by every
    organization on the installation.

    A name the organization has changed is never rewritten. The two seeders of
    storage types used to disagree about this — a module declaration left a
    changed name alone, this one overwrote it on every profile switch, and the
    only thing standing between the difference and data loss was a caller
    passing ``insert_only=True``. Which behaviour is right is not a matter of
    taste: a type's name is editable and printed, so a row carrying something
    other than the literal this table seeded is the organization's own. What
    arrives here is therefore written, and the rest of the row refreshed,
    only while the name still matches the one the seeder wrote — the same rule
    the module seeder applies.

    The name is written in the language the seed runs in, from
    ``translations`` when the entry declares that language. Which language
    that is, is decided per path, and the two answers are deliberate: a
    seeding with an actor — onboarding, a profile switch — speaks the
    request's language, the reader who is choosing; a seeding without one —
    the archived ``stypei18n01`` migration — keeps the creator's language, because a
    batch has no reader to ask, and says so itself. The reader's language
    and not the organization's because the organization has no language to
    speak of: ``Organization`` carries no such column — a session's language
    lives on the user (``User.preferred_language``) — so the seeder speaks
    the language of the person acting now.

    Repair is repeatable, not one-time, and never touches a name twice —
    renamed, that is. This pass rewrites a row only while its name is still
    THIS list's own literal, and the profile switch follows it with
    ``localize_seeded_storage_types``, which knows every seeder's literals in
    every language and moves a row still bearing any of them — including one
    a previous reader's repair wrote — into the current reader's language,
    whichever profile the row came from. So an install-day English name
    repairs at the first re-pick of the profile, a Polish one moves again for
    the reader who reads German, and the first reader does not lock the
    language. A name that differs from every literal is the organization's
    own handwriting, and nothing in this module ever rewrites it.
    """
    from app.i18n.service import get_current_lang
    from app.models.storage_type import STORAGE_TYPE_ORDER, StorageType

    lang = get_current_lang()

    for st_data in storage_types:
        localized = (st_data.get('translations') or {}).get(lang) or {}
        name = localized.get('name') or st_data['name']
        seeded_name = st_data['name']
        existing = db.scalars(
            select(StorageType)
            .where(
                StorageType.type_code == st_data['type_code'],
                StorageType.organization_id == organization_id,
            )
            .order_by(*STORAGE_TYPE_ORDER)
        ).first()
        if not existing:
            data = {k: v for k, v in st_data.items() if k != 'translations'}
            db.add(
                StorageType(**{**data, 'name': name}, organization_id=organization_id)
            )
        else:
            if not insert_only:
                existing.behavior_mode = st_data['behavior_mode']
                existing.icon = st_data.get('icon', existing.icon)
                existing.default_settings = st_data.get(
                    'default_settings', existing.default_settings
                )
                if 'context_schema' in st_data:
                    existing.context_schema = st_data['context_schema']
            # A row still bearing the literal is one nobody has renamed —
            # in either mode. insert_only exists to preserve the
            # organization's customisations, and the install-day literal is
            # not one of them: freezing it here used to leave an
            # already-seeded organization with no route to its reader's
            # language, because the switch path was the only seeding it ever
            # ran again.
            if existing.name == seeded_name and name != seeded_name:
                existing.name = name


NEUTRAL_STORAGE_TYPES: list[_StorageTypeData] = [
    {
        'name': 'Shelf / Cabinet',
        'type_code': 'SHELF',
        'behavior_mode': 'STOCK',
        'icon': 'BookOpen',
        'is_system': True,
        'default_settings': {'check_expiry': False},
        'context_schema': ['quantity', 'unit'],
        'translations': {
            'pl': {'name': 'Półka / szafa'},
            'de': {'name': 'Regal / Schrank'},
            'fr': {'name': 'Étagère / armoire'},
            'es': {'name': 'Estante / armario'},
        },
    },
    {
        'name': 'Storage Room',
        'type_code': 'STORAGE_ROOM',
        'behavior_mode': 'STOCK',
        'icon': 'Warehouse',
        'is_system': True,
        'default_settings': {'check_expiry': False},
        'context_schema': ['quantity', 'unit'],
        'translations': {
            'pl': {'name': 'Pomieszczenie magazynowe'},
            'de': {'name': 'Lagerraum'},
            'fr': {'name': 'Local de stockage'},
            'es': {'name': 'Sala de almacenamiento'},
        },
    },
    {
        'name': 'System',
        'type_code': 'SYSTEM',
        'behavior_mode': 'NONE',
        'icon': 'Settings',
        'is_system': True,
        'default_settings': {'check_expiry': False},
        'translations': {
            'pl': {'name': 'System'},
            'de': {'name': 'System'},
            'fr': {'name': 'Système'},
            'es': {'name': 'Sistema'},
        },
    },
]


def seed_neutral_storage_types(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Add neutral, vertical-agnostic storage types (no EXPIRY/FREEZING behavior).

    Args:
        db: Active SQLAlchemy session.
        organization_id: The organization that owns the seeded rows.
        insert_only: When True, existing rows are left untouched; only
            missing rows are inserted. Default ``False`` preserves the
            existing overwrite behaviour.
        commit: When True (default), commits at the end. Pass False to
            keep the seeder inside a larger transaction.
    """
    upsert_storage_types(
        db,
        NEUTRAL_STORAGE_TYPES,
        organization_id=organization_id,
        insert_only=insert_only,
    )

    if commit:
        try:
            db.commit()
            logger.info(
                '[base] Added %d neutral storage types for org %s',
                len(NEUTRAL_STORAGE_TYPES),
                organization_id,
            )
        except SQLAlchemyError:
            db.rollback()
            raise
    else:
        db.flush()


def seed_base_all(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Apply the base neutral seed: UoM + neutral storage types.

       Units of measure are installation-wide and have no owner column. Storage
       types do, and belong to *organization_id* — a profile is chosen by one
    tenant.
    """
    seed_uom(db, insert_only=insert_only, commit=commit)
    seed_neutral_storage_types(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
