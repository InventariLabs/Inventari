import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.organization import Organization
    from app.models.storage_type import StorageType


class LocationUsage(StrEnum):
    """What a location is for — assigned by the system, never by a person.

    - INTERNAL: a real shelf, room or box. Everything a person creates.
    - CUSTOMER: where consumed items go, so using something up is a move
      rather than a deleted row.
    - INVENTORY: where losses and stock corrections go.
    - PRODUCTION: where the ingredients of a production run go.

    Only INTERNAL counts towards stock; the other three are the virtual
    counterparts seeded per organization (``services/storage/_defaults.py``)
    and used as move targets (``services/items/move_service.py``). They are
    not a property of a shelf, which is why the field is not editable: a
    person setting one on their own basement rack removed its contents from
    stock, reports, purchase suggestions and scan lookup without a word.

    The Odoo-style ``supplier``/``transit``/``scrap`` roles are gone — no
    code ever assigned or read them, and nothing can set them any more.
    """

    INTERNAL = 'internal'
    CUSTOMER = 'customer'
    INVENTORY = 'inventory'
    PRODUCTION = 'production'


class StorageLocation(Base):
    """
    Specific storage location, e.g.:
    - "Cold Storage A"
    - "Rack 4 / Shelf 2"
    - "Receiving Dock"
    """

    __tablename__ = 'storage_locations'
    # short_code is unique within an organization, not globally — same rule as
    # LabelPool. A global unique let one tenant occupy a code and thereby deny
    # it to every other tenant (codes are client-supplied on create/update),
    # and the collision it produced was reported as "already in use by another
    # location", confirming the existence of a row in a foreign organization.
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'short_code',
            name='uq_storage_locations_org_short_code',
        ),
        # The stock page lists a place as a block, places by name; walking
        # them in this order lets it stop once the page is full instead of
        # sorting every group of the organization (``stockpage01``).
        Index('ix_storage_locations_org_name', 'organization_id', 'name'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        index=True,
    )
    storage_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_types.id')
    )
    #: The names the API and the contract DTOs give the type: a client meets
    #: a location type, the table keeps its storage_type spelling.
    location_type_id: Mapped[uuid.UUID | None] = synonym('storage_type_id')
    location_type: Mapped['StorageType'] = synonym('storage_type')  # type: ignore[name-defined]
    context_schema: Mapped[list[str]] = mapped_column(
        JSON, server_default='[]'
    )  # e.g. ["expiry_date", "quantity", "unit"]
    behavior_mode: Mapped[str] = mapped_column(
        String(50), server_default='STOCK'
    )  # EXPIRY, FREEZING, STOCK — derived from context_schema
    field_definitions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, server_default='[]'
    )  # custom fields: [{key, label, type, required, …}]
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    location_details: Mapped[str | None] = mapped_column(
        String(255)
    )  # e.g. "Basement", "Cold Room", "Garage"
    # No standalone index: every lookup is org-scoped, and the composite unique
    # constraint above indexes (organization_id, short_code) for exactly that.
    short_code: Mapped[str | None] = mapped_column(String(100))
    # A plain ordering number among the locations of one parent: lists and
    # walks that visit locations one after another follow it, lowest first.
    # Codes rarely say how a place is walked, so the order is a number of
    # its own; a location without one comes after the numbered ones.
    sequence: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[str] = mapped_column(
        String(50),
        default=LocationUsage.INTERNAL,
        server_default='internal',
    )
    context_tag: Mapped[str | None] = mapped_column(
        String(50), index=True
    )  # e.g. 'cold_storage', 'equipment', 'media' — NULL means universal
    settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON
    )  # notifications, default internal locations
    warehouse_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # reception_steps, delivery_steps, default locations
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id')
    )  # who created it

    # Relationships
    organization: Mapped['Organization'] = relationship(
        back_populates='storage_locations'
    )  # type: ignore[name-defined]
    parent: Mapped['StorageLocation | None'] = relationship(
        remote_side='StorageLocation.id',
        back_populates='children',
        foreign_keys='StorageLocation.parent_id',
    )
    children: Mapped[list['StorageLocation']] = relationship(
        back_populates='parent',
        foreign_keys='StorageLocation.parent_id',
    )
    user: Mapped['User'] = relationship(  # type: ignore[name-defined]
        back_populates='storage_locations', foreign_keys=[created_by]
    )
    creator: Mapped['User'] = relationship(  # type: ignore[name-defined]
        foreign_keys=[created_by], overlaps='storage_locations,user'
    )
    storage_type: Mapped['StorageType'] = relationship(
        back_populates='storage_locations', lazy='selectin'
    )  # type: ignore[name-defined]
    items: Mapped[list['Item']] = relationship(  # type: ignore[name-defined]
        back_populates='storage_location', cascade='all, delete-orphan'
    )
    stock_takes: Mapped[list['StockTake']] = relationship(  # type: ignore[name-defined]
        back_populates='storage_location', cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<StorageLocation(name="{self.name}", parent_id={self.parent_id})>'
