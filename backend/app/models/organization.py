import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

# Straight from `module_safety`, which imports nothing — `module_registry`
# re-exports the same set but pulls in the loader, and this is a model.
from app.core.module_safety import ALWAYS_ON_MODULES, is_always_on
from app.database import Base


class Organization(Base):
    """
    Organization - shared by multiple users.
    All storage_locations belong to a organization, not to a user.
    """

    __tablename__ = 'organizations'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))  # e.g. "Smith Family"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', use_alter=True)
    )

    # Modules enabled for this organization.
    #
    # Before onboarding has asked anything, an organization has exactly what is
    # not a choice: the always-on set. Onboarding then writes the chosen
    # profile's list over this.
    #
    # It used to be a hand-written list of eight, which onboarding *added* the
    # profile to rather than replacing. So the answer to "what kind of place is
    # this?" was always a union, and a household picking "Food & Home" was
    # handed the document register — numbering, accounting periods, approval
    # thresholds — that its profile does not list and is not meant to. Two
    # sources of truth, and this one won every time because it went first.
    enabled_modules: Mapped[list[str]] = mapped_column(
        JSON,
        # Effective always-on: a dropped directory named like a feature
        # must not sit in every new organisation's enablement.
        default=lambda: sorted(
            name for name in ALWAYS_ON_MODULES if is_always_on(name)
        ),
    )

    # SaaS: Modules that the organization is ALLOWED to enable (premium features)
    # If null, only standard modules are allowed.
    allowed_modules: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Global organization settings (LLM config, notifications, etc.)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {})

    # SaaS/Cloud identifier
    short_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)

    # Product profile selected during onboarding; the ids are defined in
    # ``app/seed_profiles`` (the neutral one is 'clean_core').
    # Using deferred to prevent crashes if migration is not yet applied.
    active_profile_id: Mapped[str | None] = deferred(
        mapped_column(String(50), nullable=True, server_default=None)
    )

    # Onboarding state: False until the org completes the starter-pack selection screen.
    # Using deferred to prevent crashes if migration is not yet applied.
    onboarding_completed: Mapped[bool | None] = deferred(
        mapped_column(Boolean, nullable=True, default=False, server_default='false')
    )

    # Single-module mode: the module the organization has focused on, or NULL
    # for the ordinary multi-module workspace. Deferred like the profile fields
    # so a not-yet-migrated database does not crash on import.
    focus_module: Mapped[str | None] = deferred(
        mapped_column(String(50), nullable=True, server_default=None)
    )

    # The enabled set captured on entering focus mode; leaving restores it —
    # the state before the choice, not the active profile's defaults. NULL
    # whenever the organization is not in focus mode.
    pre_focus_enabled_modules: Mapped[list[str] | None] = deferred(
        mapped_column(JSON, nullable=True, server_default=None)
    )

    # Modules the admin switched on (or back off) through POST /modules/toggle
    # while onboarding still stood open. A fresh organization holds only the
    # always-on set, so a non-empty list is an explicit decision the profile
    # question never asked about — onboarding keeps those modules instead of
    # overwriting them with the profile's chosen set, and consumes the record:
    # onboarding runs once (a second setup answers 409), so the column never
    # serves again. NULL whenever nothing was toggled by hand.
    pre_onboarding_manual_modules: Mapped[list[str] | None] = deferred(
        mapped_column(JSON, nullable=True, server_default=None)
    )

    # Localization
    currency: Mapped[str] = mapped_column(
        String(3), default='USD', server_default='USD'
    )
    timezone: Mapped[str] = mapped_column(
        String(50), default='UTC', server_default='UTC'
    )

    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # The paper this organization's office prints on: 'a4' or 'letter'.
    # NULL is "no opinion" — the country column answers (US/CA/MX print
    # Letter, everyone else A4; resolved in ``app.core.print_page_size``).
    # An explicit entry is for an office whose printer disagrees with its
    # country. Deferred like the other late columns so a not-yet-migrated
    # database does not crash on import.
    print_page_size: Mapped[str | None] = deferred(
        mapped_column(String(10), nullable=True, server_default=None)
    )

    # Issuer identity for printed documents: structured address —
    # country deliberately lives in the ``country`` column above, not here, so
    # there is exactly one source of truth for it — and the logo file path in
    # the org-scoped storage (<org_id>/organizations/logo.<ext>).
    address: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    members: Mapped[list['User']] = relationship(  # type: ignore[name-defined]
        back_populates='organization', foreign_keys='User.organization_id'
    )
    storage_locations: Mapped[list['StorageLocation']] = relationship(  # type: ignore[name-defined]
        back_populates='organization', cascade='all, delete-orphan'
    )
    storage_types: Mapped[list['StorageType']] = relationship(  # type: ignore[name-defined]
        back_populates='organization', cascade='all, delete-orphan'
    )
    creator: Mapped['User | None'] = relationship(  # type: ignore[name-defined]
        foreign_keys=[created_by], back_populates='created_organizations'
    )
    invitations: Mapped[list['OrganizationInvitation']] = relationship(
        back_populates='organization',
        cascade='all, delete-orphan',
    )
    items: Mapped[list['Item']] = relationship(  # type: ignore[name-defined]
        back_populates='organization', cascade='all, delete-orphan'
    )

    @staticmethod
    def is_module_enabled_value(enabled_modules: list | None, module_name: str) -> bool:
        """Module-enablement check against a raw ``enabled_modules`` value.

        Shared by the ORM method and the CoreAPI column getter so the
        logic lives in exactly one place.
        """
        from app.core.module_safety import is_always_on

        if is_always_on(module_name):
            return True
        if not enabled_modules:
            from app.core.module_registry import module_registry

            registered = module_registry.get(module_name)
            if registered:
                return not registered.metadata.is_premium
            return False
        return module_name in enabled_modules

    def is_module_enabled(self, module_name: str) -> bool:
        """Checks if a given module is enabled for this organization."""
        return self.is_module_enabled_value(self.enabled_modules, module_name)


class OrganizationInvitation(Base):
    """
    Invitation codes for joining an organization.

    An invitation names the address it was minted for, and keeps the trace of
    the account that redeemed it. Rows issued before that — ``invited_email``
    is NULL — stay bearer codes until they expire on their own.
    """

    __tablename__ = 'organization_invitations'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE')
    )
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    is_used: Mapped[bool] = mapped_column(default=False)
    # What the account that redeems this code becomes. The join flow used to
    # hardcode 'user', so inviting a manager meant waiting for them to arrive
    # and then promoting them.
    role: Mapped[str] = mapped_column(String(50), default='user', server_default='user')
    # An org-scoped custom role the account that redeems this code gets on top
    # of the base level in `role`. NULL for plain enum-level invitations;
    # SET NULL when the role is deleted — the code degrades to its enum level.
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('roles.id', ondelete='SET NULL'), default=None
    )
    # The address the code was issued for. Redemption checks it, so a link
    # sitting in the wrong mailbox for a week is worth nothing.
    invited_email: Mapped[str | None] = mapped_column(String(255), default=None)
    # Who redeemed it and when. `is_used` said that someone had, and the list
    # had no way to name them; SET NULL keeps the row readable after the
    # account is gone.
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), default=None
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Withdrawn by an administrator. The row stays so the history of who was
    # invited survives the withdrawal.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Relationships
    organization: Mapped['Organization'] = relationship(back_populates='invitations')
    creator: Mapped['User'] = relationship(foreign_keys=[created_by])  # type: ignore[name-defined]
