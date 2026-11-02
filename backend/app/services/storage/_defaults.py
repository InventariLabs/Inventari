from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._module_declarations import LocalizedText
from app.core.logging import get_logger
from app.i18n.service import get_current_lang
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import STORAGE_TYPE_ORDER, StorageType

if TYPE_CHECKING:
    from app.core.product_profiles import ProfileStorageLocation

logger = get_logger(__name__)


async def get_virtual_location_async(
    db: AsyncSession, organization_id: str, usage: LocationUsage
) -> StorageLocation | None:
    return await db.scalar(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.usage == usage,
        )
    )


async def ensure_virtual_locations_async(
    db: AsyncSession, organization_id: str, user_id: str
) -> None:
    system_type = await db.scalar(
        select(StorageType)
        .where(
            StorageType.type_code == 'SYSTEM',
            StorageType.organization_id == organization_id,
        )
        .order_by(*STORAGE_TYPE_ORDER)
        .limit(1)
    )
    if not system_type:
        # Without virtual locations there is nowhere to book consumption, loss
        # or production, so the organization is broken in a way that shows up
        # much later and far from here. Seeding is what failed; say so now.
        message = (
            'Storage type SYSTEM is missing — the base seed did not run. '
            'Virtual locations cannot be created for organization '
            f'{organization_id}.'
        )
        logger.error(message)
        raise RuntimeError(message)

    # A virtual location's name is written once, in the reader's language,
    # like every seeded location; the handle in settings['seed'] is what lets
    # a later pass align an untouched row without ever touching a renamed
    # one. These rows show up in the moves register and in valuation, which
    # is where an English-only name on a Polish warehouse was read.
    virtuals: list[dict[str, Any]] = [
        {
            'name': 'Consumed (Virtual)',
            'code': 'CONSUMED_VIRTUAL',
            'usage': LocationUsage.CUSTOMER,
            'translations': {
                'en': LocalizedText(name='Consumed (Virtual)'),
                'pl': LocalizedText(name='Zużyte (wirtualna)'),
                'de': LocalizedText(name='Verbraucht (virtuell)'),
                'fr': LocalizedText(name='Consommé (virtuel)'),
                'es': LocalizedText(name='Consumido (virtual)'),
            },
        },
        {
            'name': 'Inventory Loss (Virtual)',
            'code': 'LOSS_VIRTUAL',
            'usage': LocationUsage.INVENTORY,
            'translations': {
                'en': LocalizedText(name='Inventory Loss (Virtual)'),
                'pl': LocalizedText(name='Straty (wirtualna)'),
                'de': LocalizedText(name='Inventarverlust (virtuell)'),
                'fr': LocalizedText(name='Perte (virtuel)'),
                'es': LocalizedText(name='Pérdida (virtual)'),
            },
        },
        {
            'name': 'Production (Virtual)',
            'code': 'PRODUCTION_VIRTUAL',
            'usage': LocationUsage.PRODUCTION,
            'translations': {
                'en': LocalizedText(name='Production (Virtual)'),
                'pl': LocalizedText(name='Produkcja (wirtualna)'),
                'de': LocalizedText(name='Produktion (virtuell)'),
                'fr': LocalizedText(name='Production (virtuel)'),
                'es': LocalizedText(name='Producción (virtual)'),
            },
        },
    ]
    lang = get_current_lang()

    for v in virtuals:
        v_usage: LocationUsage = v['usage']  # type: ignore[assignment]
        v_code: str = v['code']  # type: ignore[assignment]
        localized = v['translations'].get(lang)
        target = localized.name if localized else v['name']
        existing = await get_virtual_location_async(db, organization_id, v_usage)
        if existing:
            # An untouched row carries exactly the name the seeder wrote —
            # recorded in its seed handle. It joins the current language; a
            # renamed row never does.
            seed = (existing.settings or {}).get('seed') or {}
            untouched = (
                seed.get('code') == v_code and seed.get('name') == existing.name
            ) or existing.name == v['name']
            if untouched and existing.name != target:
                existing.name = target
                existing.settings = {
                    **(existing.settings or {}),
                    'seed': {'code': v_code, 'name': target},
                }
            continue
        loc = StorageLocation(
            organization_id=organization_id,
            storage_type_id=system_type.id,
            name=target,
            usage=v['usage'],
            created_by=user_id,
            location_details='System location',
            settings={'seed': {'code': v_code, 'name': target}},
        )
        db.add(loc)

    await db.flush()


async def create_default_storage_locations_async(
    db: AsyncSession,
    organization_id: str,
    user_id: str,
) -> list[StorageLocation]:
    """Seed the starting locations the organization's product profile declares.

    Core knows no location names of its own: the set travels with the profile
    (``ProductProfile.default_storage_locations``), the way storage types
    already do. An organization that has not picked one yet is treated as
    neutral — the same default the seeder uses.
    """
    from app.core.product_profiles import (
        DEFAULT_PROFILE_ID,
        MAIN_STORAGE_LOCATION,
        get_profile,
    )
    from app.models.organization import Organization

    profile_id = (
        await db.scalar(
            select(Organization.active_profile_id).where(
                Organization.id == organization_id
            )
        )
        or DEFAULT_PROFILE_ID
    )
    profile = get_profile(profile_id)
    if profile is None:
        logger.error(
            'Organization %s is on unknown profile %r — no default locations seeded.',
            organization_id,
            profile_id,
        )
        await ensure_virtual_locations_async(db, organization_id, user_id)
        return []

    result = await db.execute(
        select(StorageType)
        .where(StorageType.organization_id == organization_id)
        .order_by(*STORAGE_TYPE_ORDER)
    )
    storage_type_map: dict[str, StorageType] = {}
    for st in result.scalars().all():
        # The first row in the shared order owns a code a legacy pair shares.
        storage_type_map.setdefault(st.type_code, st)

    await ensure_virtual_locations_async(db, organization_id, user_id)

    created_locations: list[StorageLocation] = []

    for default in profile.default_locations:
        created = await _seed_location_async(
            db, organization_id, user_id, default, storage_type_map, profile.id
        )
        if created is not None:
            created_locations.append(created)

    # Whatever the profile and the modules brought, the first product needs
    # an ordinary place to go. A business that unticks equipment tracking on
    # the second onboarding step used to be left with the quarantine shelf
    # alone — the equipment module is what brought its shared warehouse —
    # and the product form then sent it to set up a warehouse before
    # anything else.
    if not await _has_an_ordinary_location_async(db, organization_id):
        created = await _seed_location_async(
            db,
            organization_id,
            user_id,
            MAIN_STORAGE_LOCATION,
            storage_type_map,
            profile.id,
        )
        if created is not None:
            created_locations.append(created)

    await db.flush()
    return created_locations


async def _seed_location_async(
    db: AsyncSession,
    organization_id: str,
    user_id: str,
    default: 'ProfileStorageLocation',
    storage_type_map: dict[str, StorageType],
    profile_id: str,
) -> StorageLocation | None:
    """Create one declared starting location, or align the row already there.

    Returns the row it created; ``None`` when one was there already, or the
    type it stands on is missing.
    """
    # The language the seed runs in decides the names, the way module
    # declarations already do. A row is recognized as this declaration's by
    # its seed handle first, then by any declared name — which is what
    # catches rows written before the handles existed.
    lang = get_current_lang()
    st_type = storage_type_map.get(default.type_code)
    if st_type is None:
        # The profile asks for a type its own seed bundle should have
        # brought. Skipping used to be silent, which is how the neutral
        # profile ended up with an empty storage list nobody could explain.
        logger.error(
            'Profile %s declares default location %r on storage type %s, '
            'which organization %s does not have — location not created.',
            profile_id,
            default.name,
            default.type_code,
            organization_id,
        )
        return None

    localized = default.translations.get(lang)
    target = localized.name if localized else default.name
    declared_names = {
        default.name,
        *default.former_names,
        *(t.name for t in default.translations.values()),
    }

    rows = (
        (
            await db.execute(
                select(StorageLocation).where(
                    StorageLocation.organization_id == organization_id,
                )
            )
        )
        .scalars()
        .all()
    )
    existing = None
    for row in rows:
        seed = (row.settings or {}).get('seed') or {}
        if default.code and seed.get('code') == default.code:
            existing = row
            break
        if row.name in declared_names:
            existing = row
    if existing:
        seed = (existing.settings or {}).get('seed') or {}
        untouched = (
            default.code is not None
            and seed.get('code') == default.code
            and seed.get('name') == existing.name
        ) or existing.name in (default.name, *default.former_names)
        if untouched and existing.name != target:
            existing.name = target
            existing.settings = {
                **(existing.settings or {}),
                'seed': {
                    'code': default.code or existing.name,
                    'name': target,
                },
            }
        return None

    loc = StorageLocation(
        organization_id=organization_id,
        storage_type_id=st_type.id,
        name=target,
        created_by=user_id,
        settings=(
            {'seed': {'code': default.code, 'name': target}} if default.code else None
        ),
    )
    db.add(loc)
    return loc


async def _has_an_ordinary_location_async(
    db: AsyncSession, organization_id: str
) -> bool:
    """Whether the organization has somewhere ordinary to put a product.

    Ordinary is what the product form offers every organization: a real
    location (not a virtual counterpart), owned by no module, and not the
    quarantine shelf a damaged receipt lands on.
    """
    from app.core.product_profiles import QUARANTINE_LOCATION_CODE

    rows = (
        await db.execute(
            select(StorageLocation.settings).where(
                StorageLocation.organization_id == organization_id,
                StorageLocation.usage == LocationUsage.INTERNAL,
                StorageLocation.context_tag.is_(None),
            )
        )
    ).scalars()
    return any(
        ((settings or {}).get('seed') or {}).get('code') != QUARANTINE_LOCATION_CODE
        for settings in rows
    )
