import secrets
import string
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
)
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger
from app.i18n.service import get_current_lang
from app.models.organization import Organization
from app.models.user import User
from app.schemas._smtp import SmtpConfig
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.services._org_reads import get_by_id_async
from app.services.audit_service import log_action_async
from app.services.crypto_service import mask_settings, merge_incoming_settings

logger = get_logger(__name__)


def generate_short_id(length: int = 6) -> str:
    """Generate a random ``ORG-XXXXXX`` short id for an organization.

    Public: relocated from ``app.api.organizations.generate_org_id`` so
    Core services (e.g. ``bootstrap_service``) do not depend on the API
    layer. Renamed to ``generate_short_id`` to match the column it fills.
    """
    chars = string.ascii_uppercase + string.digits
    return 'ORG-' + ''.join(secrets.choice(chars) for _ in range(length))


async def seed_new_organization_async(db: AsyncSession, organization_id: UUID) -> None:
    """Give a freshly created organization the neutral storage types.

    Storage types are owned by a tenant, so every organization needs
       its own set from the moment it exists — SYSTEM in particular, without
       which ``ensure_virtual_locations_async`` cannot book consumption. A
       profile chosen later adds its own on top.
    """
    from app.seed_profiles.base import seed_neutral_storage_types

    await db.run_sync(
        lambda session: seed_neutral_storage_types(
            session, organization_id=organization_id, commit=False
        )
    )


async def create_organization(
    db: AsyncSession, org_in: OrganizationCreate, creator: User
) -> Organization:
    from app.services.auth_service import default_organization_name

    org_name = org_in.name or default_organization_name(
        creator.full_name, creator.preferred_language
    )
    organization = Organization(
        name=org_name,
        currency=org_in.currency,
        settings=org_in.settings or {},
        short_id=generate_short_id(),
        created_by=creator.id,
    )
    db.add(organization)
    await db.flush()
    creator.organization_id = organization.id
    creator.role = 'admin'
    await seed_new_organization_async(db, organization.id)
    # Founding a tenant is an access act the operator opens the journal to
    # answer for: the entry rides the same transaction as the row.
    await log_action_async(
        db,
        organization_id=organization.id,
        user_id=creator.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.ORGANIZATION,
        target_id=organization.id,
        snapshot={
            'name': organization.name,
            'short_id': organization.short_id,
            'currency': organization.currency,
        },
    )
    await db.flush()
    await db.refresh(organization)
    return organization


#: The legacy home of an AI purpose binding, read as a fallback by
#: ``app.core.llm.registry.binding_from_settings``.
_LEGACY_BINDING_SLOT = 'ai_default_connection_id'


def _keep_the_ai_bindings(incoming: dict, stored: dict | None) -> dict:
    """*incoming* with the AI purpose bindings put back as *stored* has them.

    The organization's settings had two doors with two keys: this route,
    which takes the settings block whole and asks for ``admin:access``, and
    ``PUT /ai-connections/bindings``, which asks for ``org:settings:write``.
    The block carries the bindings, so a custom role holding the one key
    rebound the purposes the other key was meant to guard, and a screen
    saving the block it had read before a binding was made rolled the binding
    back. The bindings are now the second door's alone: whatever the request
    carries in either of their homes — ``ai`` and the legacy
    ``modules.<owner>.ai_default_connection_id`` — the stored value stays.
    Everything else in the block is the organization's general settings, and
    stays ``admin:access``'s.
    """
    stored = stored or {}
    result = {**incoming}
    if 'ai' in stored:
        result['ai'] = stored['ai']
    else:
        result.pop('ai', None)

    stored_slots = {
        name: block[_LEGACY_BINDING_SLOT]
        for name, block in (stored.get('modules') or {}).items()
        if isinstance(block, dict) and block.get(_LEGACY_BINDING_SLOT)
    }
    modules_in = result.get('modules')
    if not isinstance(modules_in, dict):
        modules_in = {}
    if not modules_in and not stored_slots:
        return result
    modules = {
        name: (
            {k: v for k, v in block.items() if k != _LEGACY_BINDING_SLOT}
            if isinstance(block, dict)
            else block
        )
        for name, block in modules_in.items()
    }
    for name, slot in stored_slots.items():
        block = modules.get(name)
        modules[name] = {
            **(block if isinstance(block, dict) else {}),
            _LEGACY_BINDING_SLOT: slot,
        }
    result['modules'] = modules
    return result


async def apply_organization_update(
    db: AsyncSession, organization: Organization, org_in: OrganizationUpdate
) -> Organization:
    """Write the submitted fields onto *organization* and flush; no commit."""
    update_data = org_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'settings' and value is not None:
            value = merge_incoming_settings(value, organization.settings)
            value = _keep_the_ai_bindings(value, organization.settings)
        if hasattr(organization, field):
            setattr(organization, field, value)
    await db.flush()
    return organization


def refuse_smtp_settings_in_demo(settings_blob: dict | None) -> None:
    """Refuse organization-level SMTP settings on the public demo.

    A demo publishes its administrator login, so whoever is reading this is
    that administrator: a saved host would be dialled by the demo server at
    a stranger's request, and mail sent with it would escape the Mailpit
    capture. The demo declares itself through ``settings.INVENTARI_DEMO``
    (see ``docker-compose.demo.yml``); the send path ignores stored settings
    for the same reason — see ``email_service._resolve_smtp_config``. Both
    doors, one declaration.
    """
    if not settings.INVENTARI_DEMO or not settings_blob:
        return
    if 'smtp' in settings_blob:
        raise catalogue_refusal('demo_smtp_settings_locked')


def changed_fields(before: dict, after: dict) -> dict[str, dict]:
    """Top-level keys whose value differs, as ``{'before': …, 'after': …}``.

    Both sides arrive masked, so a changed SMTP password records that it
    changed without recording what to. The audit entry names the settings an
    administrator touched — "Permanent deletion" among them, which used to
    save silently and leave no trace anywhere.
    """
    keys = set(before) | set(after)
    changed = {k for k in keys if before.get(k) != after.get(k)}
    return {
        'before': {k: before.get(k) for k in sorted(changed)},
        'after': {k: after.get(k) for k in sorted(changed)},
    }


def _address_line(address: dict | None) -> str | None:
    """The address as one line a reader can take in, ``None`` when it is empty.

    The journal's Detail column prints a string as it stands and an object as
    raw JSON, and a street and a city are not a record to be read as one.
    """
    parts = [str(v).strip() for v in (address or {}).values() if v]
    return ', '.join(p for p in parts if p) or None


def _audited_view(organization: Organization) -> dict:
    # The tax ID, country and address are what every printed document says the
    # organization is: a change to them is as much the journal's business as
    # the name or the currency beside them.
    return {
        'name': organization.name,
        'currency': organization.currency,
        'tax_id': organization.tax_id,
        'country': organization.country,
        'address': _address_line(organization.address),
        **mask_settings(organization.settings or {}),
    }


async def update_organization_audited(
    db: AsyncSession,
    organization_id: UUID,
    org_in: OrganizationUpdate,
    *,
    actor_user_id: UUID,
) -> Organization:
    """Edit the organization's settings and journal what changed.

    The SMTP block is validated on save, not only on test-email — otherwise
    invalid values (bad port, malformed sender) persist silently. The row and
    its audit entry share the caller's transaction.
    """
    refuse_smtp_settings_in_demo(org_in.settings)
    if org_in.settings and 'smtp' in org_in.settings:
        try:
            SmtpConfig(**org_in.settings['smtp'])
        except PydanticValidationError as exc:
            raise catalogue_refusal(
                'smtp_config_invalid', reason=exc.errors()[0]['msg']
            ) from exc

    organization = await get_by_id_async(db, organization_id)
    if not organization:
        raise NotFoundException('organization', get_current_lang())

    before = _audited_view(organization)
    await apply_organization_update(db, organization, org_in)
    changed = changed_fields(before, _audited_view(organization))
    if changed['after']:
        await log_action_async(
            db,
            organization_id=organization.id,
            user_id=actor_user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.ORGANIZATION,
            target_id=organization.id,
            snapshot={'name': organization.name, **changed},
        )
    return organization


async def set_organization_logo(
    db: AsyncSession,
    organization_id: UUID,
    path: str | None,
    *,
    actor_user_id: UUID,
) -> None:
    """Point the organization at the logo stored at *path* (``None`` removes it).

    The column write and its audit entry ride the caller's transaction, so an
    audit failure takes the new ``logo_url`` back with it. The superseded file
    is dropped last, once both rows are flushed. The column carries the
    absolute storage path, hence the storage service rather than the
    module-facing facade.
    """
    organization = await get_by_id_async(db, organization_id)
    if not organization:
        raise NotFoundException('organization', get_current_lang())

    previous = organization.logo_url
    organization.logo_url = path
    await db.flush()
    await log_action_async(
        db,
        organization_id=organization.id,
        user_id=actor_user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ORGANIZATION,
        target_id=organization.id,
        snapshot={'logo': 'uploaded' if path else 'removed'},
    )
    # Replace: drop the previous file when it is a different path (e.g. a new
    # extension), so the storage does not accumulate dead logos.
    if previous and previous != path:
        await FileStorageService().delete(previous)


async def create_default_locations(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
) -> list:
    from app.services.storage._defaults import (
        create_default_storage_locations_async,
    )

    locations = await create_default_storage_locations_async(
        db, str(organization_id), str(user_id)
    )
    # One entry per record, not one for the batch: the journal names each
    # location the profile brought, and it rides the same transaction as the
    # rows.
    for location in locations:
        await log_action_async(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action=AuditAction.CREATE,
            target_type=AuditTargetType.STORAGE,
            target_id=location.id,
            snapshot={'name': location.name, 'usage': location.usage},
        )
    await db.flush()
    return locations
