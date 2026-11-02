"""The cross-profile catalogue of seeded storage-type names.

An organization's type picker holds rows from every profile and module it has
ever been on, each written in the language of the seeding that created it.
Localizing only the active profile's seed left the picker bilingual — six
Polish rows beside six English ones in one dropdown.

The rule the per-profile seeders already apply — a row still bearing a
literal is one nobody has renamed — extends across profiles here: the
catalogue knows every name every seeder can write, in every language, so a
row bearing ANY of them is identified as untouched whatever profile it came
from. Localization is not one-way and not final: a still-literal row follows
the reader of every seeding that runs with one, so an organization that
reads German after reading Polish is not sentenced to Polish names — while a
name that differs from every literal is the organization's own, written once
by hand, and no seeding ever rewrites it.

Why the reader's language and not the organization's: ``Organization`` has no
language column to read — the language of a session lives on the user
(:attr:`app.models.user.User.preferred_language`) — so a seeding with an
actor speaks the request's language, the person acting now. A seeding without
one (a migration) keeps what is on the row.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.seed_profiles.base import NEUTRAL_STORAGE_TYPES, _StorageTypeData

logger = get_logger(__name__)

_NAMES_BY_CODE: dict[str, dict[str, str]] | None = None


def seeded_storage_type_names() -> dict[str, dict[str, str]]:
    """Every storage-type name this installation can seed, by code and language.

    Sources: the base neutral set, every product profile's list, and every
    registered module's declarations — a picker can hold rows from all of
    them whatever profile the organization is on now. ``en`` (the
    declaration's own name) is always present; other languages appear as
    declared. Built once and cached: the declarations are static for the
    life of the process.
    """
    global _NAMES_BY_CODE
    if _NAMES_BY_CODE is not None:
        return _NAMES_BY_CODE

    names: dict[str, dict[str, str]] = {}

    def _take_data_list(types: list[_StorageTypeData]) -> None:
        for st_data in types:
            entry = {'en': st_data['name']}
            for lang, localized in (st_data.get('translations') or {}).items():
                if localized.get('name'):
                    entry[lang] = localized['name']
            names[st_data['type_code']] = entry

    from app.core.module_registry import module_registry
    from app.seed_profiles._food_home_storage_types import FOOD_HOME_STORAGE_TYPES
    from app.seed_profiles.equipment_wms import EQUIPMENT_WMS_STORAGE_TYPES

    _take_data_list(NEUTRAL_STORAGE_TYPES)
    _take_data_list(FOOD_HOME_STORAGE_TYPES)
    _take_data_list(EQUIPMENT_WMS_STORAGE_TYPES)
    for module in module_registry.get_all():
        for decl in module.metadata.storage_types:
            entry = {'en': decl.name}
            for lang, localized in decl.translations.items():
                if localized.name:
                    entry[lang] = localized.name
            names[decl.code] = entry

    _NAMES_BY_CODE = names
    return names


def localize_seeded_storage_types(
    db: Session,
    *,
    organization_id: UUID,
) -> int:
    """Move every still-literal storage-type row into the reader's language.

    A row whose name is one of the names the catalogue knows for its code —
    the install-day English or another reader's translation — is rewritten in
    the current session's language, whatever profile or module seeded it. A
    name that matches no literal is the organization's own and is left
    exactly as it stands; so is a row whose code no declaration carries.
    Rewriting is repeatable by design: the next reader who picks a profile
    moves still-literal rows again, in the other direction if their language
    differs. Only the name moves — behaviour, icon, settings and schema stay
    as the organization has them.

    The caller owns the transaction; this function neither commits nor
    flushes a commit.

    Returns:
        The number of rows rewritten (0 when the reader's language already
        stands on every literal row).
    """
    from app.i18n.service import get_current_lang
    from app.models.storage_type import StorageType

    lang = get_current_lang()
    names_by_code = seeded_storage_type_names()

    rows = db.scalars(
        select(StorageType).where(StorageType.organization_id == organization_id)
    ).all()

    rewritten = 0
    for row in rows:
        declared = names_by_code.get(row.type_code)
        if not declared:
            continue
        target = declared.get(lang, declared['en'])
        if row.name == target or row.name not in declared.values():
            continue
        row.name = target
        rewritten += 1

    if rewritten:
        logger.info(
            '[catalogue] Localized %d storage types for org %s',
            rewritten,
            organization_id,
        )
    return rewritten
