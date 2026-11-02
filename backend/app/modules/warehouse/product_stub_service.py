"""Product stub creation service for warehouse module."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api


async def quick_create_stub_async(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    barcode: str | None = None,
    user_id: UUID | None = None,
) -> Any:
    dto = await core_api.product_templates.create_stub_async(
        db, org_id, name, barcode, user_id
    )
    # No commit here: the stub rides the caller's transaction, so an import
    # that founds several stubs and then fails takes none of them back to
    # the database (the opening-stock import is the reason this matters).
    return await core_api.product_templates.get_async(db, org_id, dto.id)
