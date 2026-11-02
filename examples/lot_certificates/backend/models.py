"""The certificates this module keeps on file.

One row per certificate an organization holds: the number a supplier prints
on it, and when somebody put it on file. A receipt line names its certificate
by that number in its own ``meta_data`` (``{'lot_certificates': {'number':
...}}``); the warehouse keeps the line, this table keeps the paper.

The base is ``ModuleModelBase`` from the contract surface, and the table is
created by this module's own migration chain (``migrations/``), never by the
platform's.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.contracts import ModuleModelBase

#: The longest number the register keeps. The receiving rule refuses a longer
#: one at confirmation and the filing request at the door, so a number the
#: line accepted is never one the register cannot file.
NUMBER_MAX_LENGTH = 100


class LotCertificate(ModuleModelBase):
    """A certificate on file: the paper a lot's quality rests on."""

    __tablename__ = 'lot_certificates_certificates'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'number', name='uq_lot_certificates_org_number'
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # No ForeignKey here: this base's metadata holds the module's tables only,
    # so an ORM-level one to the core's organizations table could not resolve.
    # The migration declares the constraint and the database enforces it.
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(NUMBER_MAX_LENGTH), nullable=False)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
