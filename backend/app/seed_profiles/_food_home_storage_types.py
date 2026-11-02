from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.seed_profiles.base import _StorageTypeData, upsert_storage_types

logger = get_logger(__name__)

#: The food profile's storage types, declared at module level so the
#: cross-profile literal catalogue can read them without running a seed.
#: The neutral base schema is shared by all four types: optional fields the
#: user can opt into, with ``name``, ``quantity`` and ``unit`` always on the
#: model and never listed here.
FOOD_HOME_STORAGE_TYPES: list[_StorageTypeData] = [
    {
        'name': 'Freezer',
        'type_code': 'FREEZER',
        'behavior_mode': 'FREEZING',
        'icon': 'Snowflake',
        'is_system': True,
        'default_settings': {'check_expiry': True},
        'context_schema': [],
        'translations': {
            'pl': {'name': 'Zamrażarka'},
            'de': {'name': 'Gefrierschrank'},
            'fr': {'name': 'Congélateur'},
            'es': {'name': 'Congelador'},
        },
    },
    {
        'name': 'Fridge',
        'type_code': 'FRIDGE',
        'behavior_mode': 'EXPIRY',
        'icon': 'Refrigerator',
        'is_system': True,
        'default_settings': {'check_expiry': True},
        'context_schema': [],
        'translations': {
            'pl': {'name': 'Lodówka'},
            'de': {'name': 'Kühlschrank'},
            'fr': {'name': 'Réfrigérateur'},
            'es': {'name': 'Refrigerador'},
        },
    },
    {
        'name': 'Pantry',
        'type_code': 'PANTRY',
        'behavior_mode': 'EXPIRY',
        'icon': 'ShoppingBasket',
        'is_system': True,
        'default_settings': {'check_expiry': True},
        'context_schema': [],
        'translations': {
            'pl': {'name': 'Spiżarnia'},
            'de': {'name': 'Speisekammer'},
            'fr': {'name': 'Garde-manger'},
            'es': {'name': 'Despensa'},
        },
    },
    {
        'name': 'Medicine Cabinet',
        'type_code': 'MEDICINE_CABINET',
        'behavior_mode': 'EXPIRY',
        'icon': 'Cross',
        'is_system': True,
        'default_settings': {'check_expiry': True},
        'context_schema': [],
        'translations': {
            'pl': {'name': 'Apteczka'},
            'de': {'name': 'Medikamentenschrank'},
            'fr': {'name': 'Armoire à pharmacie'},
            'es': {'name': 'Botiquín'},
        },
    },
]


def seed_food_storage_types(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Add food-oriented storage types: FREEZER, FRIDGE, PANTRY, MEDICINE_CABINET.

    All four storage types share an identical, vertical-agnostic `context_schema`.
    Vertical-specific fields (freeze_date, expiry_date, brand, …) live on
    Category.field_definitions and are merged at item-form render time. This
    means a FREEZER and a PANTRY are storage-neutral — only the categories
    assigned to items inside them differ.

    Args:
        db: Active SQLAlchemy session.
        organization_id: The organization that owns the seeded rows.
        insert_only: When True, existing rows are left untouched.
        commit: When True (default), commits at the end.
    """
    storage_types = FOOD_HOME_STORAGE_TYPES

    upsert_storage_types(
        db,
        storage_types,
        organization_id=organization_id,
        insert_only=insert_only,
    )

    if commit:
        try:
            db.commit()
            logger.info('[food_home] Added %d food storage types', len(storage_types))
        except SQLAlchemyError:
            db.rollback()
            raise
    else:
        db.flush()
