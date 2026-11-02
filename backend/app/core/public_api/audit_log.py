"""
Module-safe access to the immutable AuditLog table (read and write).

The AuditLog is populated by service-layer calls (e.g. ``log_purge_async``)
and by database triggers. The ``audit_log_immutable`` DB trigger blocks
UPDATE and DELETE at the storage layer — existing rows are append-only.

Modules should never query ``AuditLog`` directly; this API keeps the
public contract stable and isolates raw SQL from consumers.

``log_action_async`` provides the write surface so modules that follow
the Golden Path can instrument their mutation paths with audit entries
without importing ``app.services`` directly. It returns ``None``
deliberately (fire-and-forget for module code paths).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditLogDTO
from app.core.logging import get_logger
from app.services import audit_service

logger = get_logger(__name__)


class CoreAuditLogAPI:
    """Public Core API for module-safe audit-trail reads + writes.

    Reads (list_for_*) return ``AuditLogDTO`` instances. Writes
    (``log_action_async``) delegate to the internal
    ``audit_service.log_action_async`` writer and return ``None``
    (fire-and-forget). Mutation services in modules must go through this
    surface rather than importing ``app.services`` directly -- per
    AGENTS.md Golden Path, modules touch Core data through CoreAPI only.
    """

    async def list_for_org_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        user_id: UUID | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
        after: tuple[datetime, UUID] | None = None,
        known_total: int | None = None,
    ) -> tuple[list[AuditLogDTO], int]:
        """Return audit entries for one organization, newest first.

        Filters compose with AND semantics. Org-scoped: entries from
        other organizations are never returned. Each DTO carries an
        optional ``user_email`` resolved via LEFT JOIN on ``users.id``
        — the underlying ``user_id`` UUID stays on the row for
        precision (emails mutate, UUIDs do not). Returns
        ``(dtos, total)`` so callers can build a paginated envelope.

        ``actor`` keeps a key's work apart from a person's: ``'api_key'``
        for entries a key wrote, ``'human'`` for the rest.

        The next page is asked for with the last entry of the previous one
        (``after``: its instant and id) rather than a larger ``offset``, and a caller that kept the count from the first page
        passes it back as ``known_total``.
        """
        entries, total = await audit_service.list_for_org_async(
            db,
            organization_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            actor=actor,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            after=after,
            known_total=known_total,
        )
        dtos: list[AuditLogDTO] = []
        for entry, user_email in entries:
            dto = AuditLogDTO.model_validate(entry)
            dto.user_email = user_email
            dtos.append(dto)
        return dtos, total

    async def list_target_types_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[str]:
        """The distinct target types this organization's log actually holds."""
        return await audit_service.list_target_types_async(db, organization_id)

    async def list_for_target_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        target_type: str,
        target_id: UUID,
        *,
        limit: int = 200,
    ) -> list[AuditLogDTO]:
        """Return audit entries for one (target_type, target_id), newest first."""
        entries = await audit_service.list_for_target_async(
            db,
            organization_id,
            target_type,
            target_id,
            limit=limit,
        )
        return [AuditLogDTO.model_validate(e) for e in entries]

    async def log_action_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: AuditAction,
        target_type: str,
        target_id: UUID,
        snapshot: dict[str, Any] | None = None,
        reason: str | None = None,
        meta_data: dict[str, Any] | None = None,
    ) -> None:
        """Module-safe write surface for audit entries.

        Thin wrapper over ``audit_service.log_action_async``. Modules
        must call this through CoreAPI rather than importing the
        service-layer helper directly (AGENTS.md Golden Path). Flushes
        inside the caller's transaction; does NOT commit -- caller
        owns the boundary.

        Returns ``None`` deliberately: the call is fire-and-forget for
        module code paths. Returning the persisted DTO would force
        every caller to await a value they never read, and would
        require us to materialise ``id`` + ``created_at`` (which need a
        real DB session to populate -- the in-process default values
        only fire after a real flush, so a unit-test ``MagicMock`` for
        ``db`` cannot satisfy ``AuditLogDTO``'s required UUID/datetime
        fields). Read paths that need the DTO still have
        ``list_for_org_async`` / ``list_for_target_async``.
        """
        await audit_service.log_action_async(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            snapshot=snapshot,
            reason=reason,
            meta_data=meta_data,
        )
