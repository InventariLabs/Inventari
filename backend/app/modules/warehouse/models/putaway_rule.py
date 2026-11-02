"""PutawayRule model — automated receiving location routing.

Lives in the ``warehouse`` module because:
  - Putaway is a receiving-decision concern (consumer is the receipt
    executor in ``_stock_executor_receipt.py``).
  - No Core-level concept is needed; the model maps domain-specific
    matching criteria to a target storage location.
  - Follows the same module-local precedent as
    ``ReorderRule`` in ``purchase_orders/models.py``.

Each rule matches a receipt line on up to four optional keys
(``product_template_id``, ``category_id``, ``context_tag``,
``storage_type_code``); at least one must be non-null
(enforced by CHECK constraint). Resolution specificity
descends in that order — the resolver picks the most specific
match, falling back to doc.target_location_id when no rule applies.
``priority`` (lower wins) breaks ties within the same specificity tier.
``is_active`` allows soft-deactivation without losing history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.core.module_sdk import CoreModelBase

if TYPE_CHECKING:
    from .putaway_rule_location import PutawayRuleLocation


class PutawayRule(CoreModelBase):
    """Auto-route receiving lines to a target storage location.

       A rule matches when ANY of its non-null match keys matches the line
    (OR semantics) — e.g. a rule with ``category_id=DAIRY`` and
       ``storage_type_code=FREEZER`` fires for a DAIRY line headed anywhere,
       or for any line headed to a FREEZER. When several keys of one rule
       match, the most specific one decides the rule's ranking tier
       (product_template > category > context_tag > storage_type_code);
       within the same tier ``priority`` (lower wins) decides.
    """

    __tablename__ = 'putaway_rules'
    __table_args__ = (
        CheckConstraint(
            '(product_template_id IS NOT NULL) OR '
            '(category_id IS NOT NULL) OR '
            '(context_tag IS NOT NULL) OR '
            '(storage_type_code IS NOT NULL)',
            name='ck_putaway_rules_at_least_one_match',
        ),
        Index('ix_putaway_rules_org_priority', 'organization_id', 'priority'),
        Index('ix_putaway_rules_org_product', 'organization_id', 'product_template_id'),
        Index('ix_putaway_rules_org_category', 'organization_id', 'category_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )

    # Match keys (all optional, but at least one required via CHECK)
    product_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('categories.id', ondelete='CASCADE'),
        nullable=True,
    )
    context_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_type_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: The name the API gives this column: a client meets a location type,
    #: the table keeps its storage_type spelling.
    location_type_code: Mapped[str | None] = synonym('storage_type_code')

    # The rule's shelves, in the order the resolver walks them. Lives on
    # ``PutawayRuleLocation`` rows — an ordered list replaced the single
    # target column, because the first shelf filling up used to be the end
    # of the conversation.

    # Tie-breaker within the same specificity tier
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default='true'
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    locations: Mapped[list[PutawayRuleLocation]] = relationship(
        'PutawayRuleLocation',
        order_by='PutawayRuleLocation.position',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
