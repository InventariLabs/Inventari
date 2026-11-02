"""Products whose put-away never asks for a home shelf.

The put-away screen offers to make the shelf a worker used the product's home.
A person who keeps a product wherever it fits answers "do not ask again for
this product"; that answer is one row here, and removing the row asks again.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class PutawayHomeSilenced(CoreModelBase):
    """One product the home-shelf question is not asked about."""

    __tablename__ = 'putaway_home_silenced'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_putaway_home_silenced_org_product',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
