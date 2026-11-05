"""API Keys module — Personal Access Tokens for machine-to-machine auth."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ApiKey(Base):
    """An API key that authenticates external scripts, automations, and services."""

    __tablename__ = 'api_keys'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )

    name = Column(String(255), nullable=False)

    # SHA-256 hash of the raw key — the raw key is NEVER stored
    hashed_key = Column(String(64), nullable=False, unique=True, index=True)

    # The start of the raw key, to tell keys apart by eye ("inv_live_a1b2c3"):
    # api_key_service.SHOWN_KEY_CHARACTERS of its random characters, no more.
    key_prefix = Column(String(15), nullable=False)

    #: The permission keys the key may use, chosen from its creator's when it
    #: was issued. The whole of what it may do: its owner's grants are not
    #: consulted on a request.
    permissions = Column(JSONB, nullable=False, default=list, server_default='[]')

    #: Empty for an ordinary key. Otherwise the names of scopes modules
    #: registered (``app.core.api_key_auth``): the key then reaches only the
    #: endpoints guarding their permissions — a print agent's key cannot read
    #: the inventory. Not ``scopes``: the module's second revision drops a
    #: column of that name, and replaying it must not take this one with it.
    scope_names = Column(JSONB, nullable=False, default=list, server_default='[]')

    is_active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user = relationship('User', lazy='selectin')
