import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.storage_location import StorageLocation


class StorageType(Base):
    """
    Storage location types - can be system-wide or organization-specific.

    System types (is_system=True) are seeded by Core (Shelf, Storage Room,
    System) and extended by the active product profile, which adds the types
    its vertical needs — see ``app/seed_profiles`` for what each one seeds.

    Organization types (organization_id set, is_system=False):
    - Custom types created by organizations
    """

    __tablename__ = 'storage_types'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id')
    )  # NULL = global/system type
    name: Mapped[str] = mapped_column(String(100))
    type_code: Mapped[str] = mapped_column(
        String(50)
    )  # Unique within organization or globally for system types
    behavior_mode: Mapped[str] = mapped_column(
        String(50), default='STOCK'
    )  # STOCK (neutral default), EXPIRY, FREEZING, NONE — set explicitly per vertical

    # JSON array of field keys visible in this storage context
    # e.g., ["brand", "quantity", "unit"] or ["brand", "expiry_date", "quantity"] for expiry-tracked contexts
    context_schema: Mapped[list[str]] = mapped_column(JSON, server_default='[]')

    # JSON array of custom field definitions (for user-defined fields specific to this storage type)
    # e.g., [{"key": "voltage", "label": "Voltage", "type": "text", "required": false}]
    field_definitions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, server_default='[]'
    )

    icon: Mapped[str | None] = mapped_column(String(100))
    is_system: Mapped[bool] = mapped_column(
        default=False
    )  # System types cannot be deleted; renaming them is allowed
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    default_settings: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Relationships
    storage_locations: Mapped[list['StorageLocation']] = relationship(
        back_populates='storage_type'
    )  # type: ignore[name-defined]
    organization: Mapped['Organization'] = relationship(back_populates='storage_types')  # type: ignore[name-defined]


#: The one order every reader of an organization's storage types uses.
#: Without an ORDER BY Postgres answers in heap order, which follows the
#: table's physical layout and not the data; two rows sharing a type code
#: (a legacy shape — creation refuses it now) would then resolve their
#: collision by accident. Whoever takes "the row for this code" takes the
#: first one in this order.
STORAGE_TYPE_ORDER = (func.lower(StorageType.name), StorageType.name, StorageType.id)
