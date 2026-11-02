import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(Base):
    """
    Represents a named set of permissions that can be assigned to users.

    Every role belongs to exactly one organisation. A row without one used to
    be legal and was read as belonging to all of them — the roles list, the
    permission check and a user's own roles each asked for
    ``organization_id = :org OR organization_id IS NULL`` — so a single row
    granted its permissions in every organisation of the installation.

    ``is_system`` marks a role an organisation's administrator may not edit.
    The four built-in levels are not rows at all: they live on ``User.role``
    and their permissions are computed, which is why nothing here is needed to
    make them global.
    """

    __tablename__ = 'roles'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id'), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100))
    # List of permission strings, e.g. ['items:read', 'pos:sell']
    permissions: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default='[]'
    )
    # System roles cannot be deleted by org admins
    is_system: Mapped[bool] = mapped_column(default=False, server_default='false')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    organization: Mapped['Organization'] = relationship(foreign_keys=[organization_id])  # type: ignore[name-defined]
    user_roles: Mapped[list['UserRole']] = relationship(
        back_populates='role', cascade='all, delete-orphan'
    )


class UserRole(Base):
    """Many-to-many join between users and roles."""

    __tablename__ = 'user_roles'

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('roles.id'), primary_key=True)

    user: Mapped['User'] = relationship(back_populates='user_roles')  # type: ignore[name-defined]
    role: Mapped['Role'] = relationship(back_populates='user_roles')
