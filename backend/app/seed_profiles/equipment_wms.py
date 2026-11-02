"""
Equipment / WMS seed profile.

Contains:
  - WMS-oriented storage types with neutral behavior_mode (STOCK/NONE).

Note: equipment *categories* (LAPTOP, DESKTOP, SERVER, etc.) and the
default *storage locations* ("Server Room", "IT Storage") are seeded
automatically by the equipment module's ``system_on_enable()`` from its
metadata declarations when the module is enabled for an organization.
This profile only provides the storage location types suitable for
equipment tracking.
"""

from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.seed_profiles.base import (
    _StorageTypeData,
    seed_base_all,
    upsert_storage_types,
)

logger = get_logger(__name__)


def seed_equipment_storage_types(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Add WMS-oriented storage types: no EXPIRY/FREEZING behavior.

    Only the two types the equipment module does not declare itself: the
    module seeds "Server Room" and "IT Storage / Warehouse" with the
    equipment field set (serial number, manufacturer, model, IP, status),
    and this profile used to seed near-duplicates of both ("IT Rack /
    Server Room", "Asset Storage") with the neutral set — two entries that
    meant the same place and chose their fields at random. The duplicates
    are retired: fresh installations never see them, and existing rows are
    held back from the picker like every other retired code.

    Args:
        db: Active SQLAlchemy session.
        organization_id: The organization that owns the seeded rows.
        insert_only: When True, existing rows are left untouched.
        commit: When True (default), commits at the end.
    """
    storage_types = EQUIPMENT_WMS_STORAGE_TYPES

    upsert_storage_types(
        db,
        storage_types,
        organization_id=organization_id,
        insert_only=insert_only,
    )

    if commit:
        try:
            db.commit()
            logger.info(
                '[equipment_wms] Added %d equipment storage types',
                len(storage_types),
            )
        except SQLAlchemyError:
            db.rollback()
            raise
    else:
        db.flush()


#: The equipment profile's storage types, declared at module level so the
#: cross-profile literal catalogue can read them without running a seed.
EQUIPMENT_WMS_STORAGE_TYPES: list[_StorageTypeData] = [
    {
        'name': 'Tool Room',
        'type_code': 'TOOL_ROOM',
        'behavior_mode': 'STOCK',
        'icon': 'Wrench',
        'is_system': True,
        'default_settings': {'check_expiry': False},
        'context_schema': ['quantity', 'unit'],
        'translations': {
            'pl': {'name': 'Narzędziownia'},
            'de': {'name': 'Werkzeugraum'},
            'fr': {'name': "Salle d'outils"},
            'es': {'name': 'Sala de herramientas'},
        },
    },
    {
        'name': 'Maintenance Bay',
        'type_code': 'MAINTENANCE_BAY',
        'behavior_mode': 'NONE',
        'icon': 'Hammer',
        'is_system': True,
        'default_settings': {'check_expiry': False},
        'context_schema': ['quantity', 'unit'],
        'translations': {
            'pl': {'name': 'Stanowisko serwisowe'},
            'de': {'name': 'Wartungsbereich'},
            'fr': {'name': 'Atelier de maintenance'},
            'es': {'name': 'Zona de mantenimiento'},
        },
    },
]


def seed_equipment_wms(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Apply the Equipment/WMS profile: base + equipment storage types.

    ``organization_id`` owns the seeded storage types. Equipment categories
    and default locations are seeded per organization by the module's
    ``system_on_enable()``, not by this profile.
    """
    seed_base_all(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
    seed_equipment_storage_types(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
