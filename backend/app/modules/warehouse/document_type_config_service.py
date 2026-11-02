from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger

from .models import DocumentTypeConfig
from .schemas import DocumentTypeConfigUpdate

logger = get_logger(__name__)


async def get_type_config(
    db: AsyncSession, org_id: UUID, document_type: str
) -> DocumentTypeConfig | None:
    """The organization's configuration for one document type, if it set one.

       Read on the create path (defaults, partner requirement) and by the
    numbering service. Until then the endpoints stored these settings
       and nothing acted on them: the API accepted a configuration and the
       documents ignored it.
    """
    result = await db.scalars(
        select(DocumentTypeConfig).where(
            DocumentTypeConfig.organization_id == org_id,
            DocumentTypeConfig.document_type == document_type,
        )
    )
    return result.first()


async def list_type_configs(db: AsyncSession, org_id: UUID) -> list[DocumentTypeConfig]:
    result = await db.scalars(
        select(DocumentTypeConfig)
        .where(DocumentTypeConfig.organization_id == org_id)
        .order_by(DocumentTypeConfig.document_type)
    )
    return list(result.all())


def _apply_update(existing: DocumentTypeConfig, data: dict[str, Any]) -> None:
    validated = DocumentTypeConfigUpdate(**data)
    updates = validated.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(existing, field, value)


async def upsert_type_config(
    db: AsyncSession,
    org_id: UUID,
    document_type: str,
    data: dict[str, Any],
) -> DocumentTypeConfig:
    await acquire_advisory_lock(db, f'type_config:{org_id}:{document_type}')
    result = await db.scalars(
        select(DocumentTypeConfig).where(
            DocumentTypeConfig.organization_id == org_id,
            DocumentTypeConfig.document_type == document_type,
        )
    )
    existing = result.first()

    if existing:
        _apply_update(existing, data)
        await db.flush()
        await db.refresh(existing)
        return existing

    config = DocumentTypeConfig(
        organization_id=org_id,
        document_type=document_type,
        default_source_location_id=data.get('default_source_location_id'),
        default_target_location_id=data.get('default_target_location_id'),
        sequence_format=data.get('sequence_format', '{TYPE}/{YEAR}/{SEQ:05d}'),
        require_partner=data.get('require_partner', False),
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)
    return config


async def delete_type_config(
    db: AsyncSession, org_id: UUID, document_type: str
) -> DocumentTypeConfig:
    result = await db.scalars(
        select(DocumentTypeConfig)
        .where(
            DocumentTypeConfig.organization_id == org_id,
            DocumentTypeConfig.document_type == document_type,
        )
        .with_for_update()
    )
    config = result.first()
    if not config:
        raise ServiceRejectionError('document_type_config_not_found')
    await db.delete(config)
    await db.flush()
    return config
