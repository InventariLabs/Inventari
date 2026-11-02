"""The organization's own ceiling on how many items it may hold.

Both doors into the warehouse — the form and the scan — ask this one
question, so a limit is reached the same way whichever door the product
arrives through.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contributions import contribution_registry
from app.core.exceptions import QuotaExceededError
from app.i18n.service import get_current_lang, get_error_message


async def check_item_quota_async(org_id: UUID, db: AsyncSession) -> None:
    """Raise ``QuotaExceededError`` when the org is at the configured item limit."""
    if not await contribution_registry.check_quota(org_id, 'max_items', db):
        raise QuotaExceededError(
            get_error_message('item_limit_reached', get_current_lang())
        )
