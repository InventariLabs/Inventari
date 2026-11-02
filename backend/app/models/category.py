import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Category(Base):
    """
    Classification groups for inventory items.

    Grouping roles (see field comments for details): ``context_tag`` says WHO
    owns the category (a module, feeding module_scope), ``group_label`` says
    HOW the organisation groups categories for itself (user-editable).

    Examples by vertical:
    - Food: Pork, Dairy, Dry goods
    - Equipment: Power Tools, Safety Gear, Vehicles
    - Library: Fiction, Non-fiction, Periodicals
    - HoReCa: Beverages, Linens, Cooking Equipment
    """

    __tablename__ = 'categories'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str | None] = mapped_column(String(100), index=True)
    # Two neighbouring fields, two different roles — do not conflate:
    # - context_tag: WHO owns this category (a module / vertical, set in the
    #   module's declarations; feeds module_scope). Never user-editable.
    # - group_label: HOW the organisation groups categories for itself —
    #   a free-form label the user types in the category form and the
    #   categories filter groups by. A label, not a code: kept verbatim,
    #   no enum, no upper().
    context_tag: Mapped[str | None] = mapped_column(
        String(100), index=True
    )  # Neutral context label for vertical-agnostic routing (e.g. 'cold_storage', 'equipment', 'media').
    group_label: Mapped[str | None] = mapped_column(String(50))
    icon: Mapped[str | None] = mapped_column(String(100))
    # Category Visual Identity v2 (2026-07-04).
    # ``emoji``: user-overridable single-glyph (e.g. "🥚"). NULL = "let the
    #   frontend cascade resolve via keyword guess / vertical default".
    # ``color``: a Tailwind palette KEY (e.g. "indigo"), not a hex value,
    #   because Tailwind's JIT purge strips dynamic ``bg-[#...]`` classes.
    # Both nullable so the migration is zero-downtime and existing rows get
    # cascade resolution on day 1 with no backfill required.
    emoji: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The removal strategy ('FIFO' or 'FEFO') a product minted under this
    # category starts with. Read once, when the product is created; the
    # product's own ``removal_strategy`` is what the stock engine reads.
    default_removal_strategy: Mapped[str | None] = mapped_column(String(10))

    # Module integration fields
    module_name: Mapped[str | None] = mapped_column(String(50), index=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # JSON array of field definitions
    # Example: [{"key": "author", "label": "Author", "type": "text", "visible": true, "required": false}]
    field_definitions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, server_default='[]'
    )

    # Relationships
    organization: Mapped['Organization'] = relationship(backref='custom_categories')  # type: ignore[name-defined]
    items: Mapped[list['Item']] = relationship(back_populates='category')  # type: ignore[name-defined]

    def __repr__(self):
        return f'<Category(name="{self.name}", tag="{self.context_tag}")>'
