"""
ModuleInstallation — persists per-module installation state.

Tracks installed version per module so that ModuleRegistry can detect
upgrades and call on_install / on_upgrade hooks accordingly.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModuleInstallation(Base):
    __tablename__ = 'module_installations'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    installed_version: Mapped[str] = mapped_column(String(50))
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
