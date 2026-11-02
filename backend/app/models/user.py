import functools
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Default language from environment variable, fallback to 'en'
@functools.cache
def get_default_language() -> str:
    """Get default language from environment or return 'en'."""
    import os

    return os.getenv('DEFAULT_LANGUAGE', 'en')


class User(Base):
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Language preference
    preferred_language: Mapped[str] = mapped_column(
        String(10),
        default=get_default_language,
        server_default=get_default_language(),
    )

    # Multi-user support
    role: Mapped[str] = mapped_column(String(50), default='user')  # 'admin', 'user'
    is_active: Mapped[bool] = mapped_column(default=False, server_default='false')
    is_superuser: Mapped[bool] = mapped_column(
        default=False, server_default='false', index=True
    )

    # SaaS Blocking
    is_blocked: Mapped[bool] = mapped_column(default=False, server_default='false')
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocking_reason: Mapped[str | None] = mapped_column(String(500))

    # Brute-force protection
    failed_login_count: Mapped[int | None] = mapped_column(
        BigInteger, default=0, server_default='0'
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', use_alter=True),
        index=True,
    )

    # Relationships
    organization: Mapped['Organization'] = relationship(  # type: ignore[name-defined]
        back_populates='members', foreign_keys=[organization_id], lazy='selectin'
    )
    created_organizations: Mapped[list['Organization']] = relationship(  # type: ignore[name-defined]
        back_populates='creator', foreign_keys='Organization.created_by'
    )
    storage_locations: Mapped[list['StorageLocation']] = relationship(  # type: ignore[name-defined]
        back_populates='user', cascade='all, delete-orphan'
    )
    stock_takes: Mapped[list['StockTake']] = relationship(  # type: ignore[name-defined]
        back_populates='user', cascade='all, delete-orphan'
    )
    user_roles: Mapped[list['UserRole']] = relationship(  # type: ignore[name-defined]
        back_populates='user', cascade='all, delete-orphan'
    )

    @property
    def organization_name(self) -> str | None:
        """Helper to get organization name for admin views."""
        return self.organization.name if self.organization else None


class RegistrationRequest(Base):
    __tablename__ = 'registration_requests'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    token: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    preferred_language: Mapped[str] = mapped_column(
        String(10), default='en', server_default='en'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_rejected: Mapped[bool] = mapped_column(default=False, server_default='false')

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    approved_by: Mapped['User | None'] = relationship(foreign_keys=[approved_by_id])
