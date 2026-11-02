"""Putaway rule → ordered list of target locations.

One rule, many shelves, in order: the resolver walks the list against
capacity and settles on the first shelf the goods fit. The list replaced
the rule's single ``target_location_id`` column — the data migration made
every existing target the head of its rule's list — so this table is the
only place a rule's shelves live.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.module_sdk import CoreModelBase


class PutawayRuleLocation(CoreModelBase):
    """One shelf on a rule's ordered list.

    ``position`` decides the walking order — lower tries first. Unique per
    (rule, location): the same shelf twice on one list says nothing twice.
    """

    __tablename__ = 'putaway_rule_locations'
    __table_args__ = (
        UniqueConstraint(
            'rule_id',
            'location_id',
            name='uq_putaway_rule_locations_rule_loc',
        ),
        Index('ix_putaway_rule_locations_rule', 'rule_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('putaway_rules.id', ondelete='CASCADE'),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default='0'
    )

    location = relationship('StorageLocation')
